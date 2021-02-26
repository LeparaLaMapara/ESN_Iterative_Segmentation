import torch
import numpy as np
import pandas as pd
import argparse

import logging    
from utils.logger import get_logger
from tqdm import tqdm

from torch.utils import tensorboard
import json, os, sys
import time

import errno
import os


sys.path.append('/')
from utils.utils import LevelSetDataset
from utils.metrics import iou_pytorch, pixel_segementation_evaluation 
from utils.PytorchEarlyStopping import EarlyStopping
from utils.loss import weighted_binary_cross_entropy, generalised_loss

# from model.RNN  import  ImageLSTM, ImageGRU, ImageRNN, ESN # vanilla models
# from model.ConvRNN import CRNN #conv-rnn/lstm/gru
# from model.ConvRNN import ResCRNN # pretrained resnet-rnn/lstm/gru

from model.ConvRNN import CESN # conv-esn
# from model.ConvRNN import ResCESN # pretrained resnet-esn
# from models.Conv3D import    CNN3D

if __name__=="__main__":

    # parse augments

    in_channels=3, sample_size=256, sample_duration=16, num_classes=100,
                hidden_size=512, num_layers=1, leaking_rate=0.05,spectral_radius=0.9, sparsity=0.2

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-name", type=str, default='test_', required=True, help="Name of the run [CNN3D]")
    parser.add_argument("--data-path", type=str, required=True, help="Path to where the data is located")
    parser.add_argument("--save-path", type=str, required=True, help="Path to where runs will be written")

    parser.add_argument("--num-epochs", type=int, default=500, help="Number of training epochs [500]")
    parser.add_argument("--batch-size", type=int, default=32, help="Number of examples to use in a batch [32]")
    parser.add_argument("--learning-rate", type=float, default=0.1, help="Learning rate for training [0.1]")

    parser.add_argument("--num-frames", type=int, default=95, help="Length of the sequences for each image [95]")
    parser.add_argument("--num-past-step", type=int, default=1, help="Number of steps to use in input [1]")
    parser.add_argument("--num-future-step", type=int, default=1, help="Number of time steps in the future for predictions [1]")
    parser.add_argument("--image-dimension", type=int, default=32, help="Dimensions to resize the images [32]")
    parser.add_argument("--threshold", type=float, default=0.5, help="Pixel cutoff to create mask [0.5]")


    parser.add_argument("--in-channels", type=int, default=3, help="Input channel for the 1st conv layer [3]")
    parser.add_argument("--hidden",  type=int, default=512, help="Number of hidden units in the 1st  fully connected layer [512]")
    parser.add_argument("--num-classes", type=int, default=1024, help="Number of pixel classes to be predicted [1024]")
    parser.add_argument("--num_layers", type=int, default=1, help="Number of layers in the recurrent unit [1]")
    parser.add_argument("--sample-size", type=int, default=128 , help=" [128]")
    parser.add_argument("--sample-duration", type=int, default=16, help=" [16]")
    parser.add_argument("--leaking-rate", type=float, default=0.01, help="Leak rate for leaky ESN [0.01]")
    parser.add_argument("--spectral-radius", type=float, default=0.9, help="Scaling of reservoir matrix [0.9]")
    parser.add_argument("--sparsity", type=float, default=0.2, help="Percentage of neurons with zeros in the reservoir matrix [0.2]")

    parser.add_argument("--seed", type=int, default=0, help="Seed for random number generation [0]")

    args = parser.parse_args()

    args.save_path = os.path.abspath(args.save_path)
    args.data_path = os.path.abspath(args.data_path)
    run_path = os.path.join( args.save_path, args.run_name)
    os.makedirs(run_path, exist_ok=True)

    # logging
    logger = get_logger(run_path)

    # set random seed
    if args.seed:
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
    else:
        args.seed = np.random.randint(0, 100)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)

    # tensorboad logs
    tb_log_path = os.path.join(run_path,"tensorboard_logs", args.run_name)
    os.makedirs(tb_log_path, exist_ok=True)
    summary_witer = tensorboard.SummaryWriter(tb_log_path, filename_suffix=args.run_name)

    # checkpoints
    checkpoints_path = os.path.join(run_path, "checkpoints")
    os.makedirs(checkpoints_path, exist_ok=True)
    try:
        os.remove(os.path.join(checkpoints_path, "*.pt.*"))
    except FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT)):
        pass

    # log all parameters
    logger.info("Commnad-line arguments")
    for arg, value in sorted(vars(args).items()):
        logger.info(f"arguments {args}: {value}")
    
     # data loader
    logger.info("Creating dataset......")
    ls_dataset = LevelSetDataset(
        input_image_path=os.path.join(args.data_path,"images"),
        target_image_path=os.path.join(args.data_path,"labels"),
        threshold=args.threshold,
        num_past_steps=args.num_past_step,
        num_future_steps=args.num_future_step,
        image_dimension=args.image_dimension,
        num_frames=args.num_frames ,
        valid_split= 0.1,     
        train_split= 0.8,
        training_mode='train'
        )

    ls_train_ds = ls_dataset.create_set(batch_size=args.batch_size, shuffle=True, pin_memory=True, num_workers=4)
    ls_valis_ds = ls_dataset.create_set(batch_size=args.batch_size, shuffle=True, pin_memory=True, num_workers=4)

    # define model
    logger.info("Creating model......")
    model = CESN(
        in_channels=args.in_channels,
        sample_size=args.sample_size,
        sample_duration=args.sample_duration,
        drop_p=args.dropout_prob, 
        hidden_size=args.hidden,
        num_layers=args.num_layers,
        rnn_unit=args.rnn_unit,
        num_classes=args.num_classes,
        leaking_rate=args.leaking_rate,
        spectral_radius=args.spectral_radius,
        sparsity=args.sparsity
    )

                
    # device to perform computation (CPU or GPU)
    device   = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    # initliaze optimizer 
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)

    # learning rate schedular
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=int(args.num_epochs/5), gamma=0.1)

    # loss function
    loss_function = weighted_binary_cross_entropy

    # early_stopping = EarlyStopping(name=run_path,patience=10, verbose=True)  
    logger.info("Training starting........")

    # to track the training loss as the model trains
    train_running_loss     = []
    # to track the validation loss as the model trains
    valid_running_loss     = []
    # to track the average training loss per epoch as the model trains
    train_epoch_loss       = []
    # to track the average validation loss per epoch as the model trains
    valid_epoch_loss       = [] 
    # to track the validation dice as the model trains
    valid_running_dice     = []
    # to track the validation accuracy as the model trains
    valid_running_accuracy = []
    # to track the validation precision as the model trains
    valid_running_precision = []
    # to track the validation recall as the model trains
    valid_running_recall   = []
    # to track the average validation dice per epoch as the model trains
    valid_epoch_dice       = []
    # to track the average validation accuracy per epoch as the model trains
    valid_epoch_accuracy   = []
    # to track the average validation precision per epoch as the model trains
    valid_epoch_precision   = []
    # to track the average validation recall per epoch as the model trains
    valid_epoch_recall      = []
    # capture the time to start training
    epoch_start_time = time.time()
    best_valid_iou   = -np.inf
    best_valid_epoch = 0
    epoch_buffer     = 10
    try:
        for epoch in np.arange(args.num_epochs):
            model.train()
            for batch_idx, (inputs, labels, names) in enumerate(ls_train_ds):

                # load data and move data to GPU's
                inputs = inputs.to(device, non_blocking=True)
                labels = labels.to(device, non_blocking=True)

                # forward-propogation
                outputs = model(inputs)

                loss = loss_function(labels, outputs)

                # back-propagation
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()
                scheduler.step() 

                train_running_loss.append(loss.detach().item())
                    
                # clear variables from memory
                del inputs, labels, outputs 
                torch.cuda.empty_cache()

            model.eval()
            with torch.no_grad(): # do not calculate gradient and save memory usage
                for batch_idx, (inputs, labels, names) in enumerate(ls_valis_ds):

                    # load data and move data to GPU's
                    inputs = inputs.to(device, non_blocking=True)
                    labels = labels.to(device, non_blocking=True)

                    # forward-propogation
                    outputs = model(inputs) 
                    loss = loss_function(labels, outputs)

                    # compute the metrics
                    outputs = (outputs >= args.threshold)*1
                    iou     =  iou_pytorch(outputs, labels.detach().item())
                    f1, precision, recall  = pixel_segementation_evaluation(labels.cpu().detach().numpy().reshape(-1),
                    outputs.cpu().detach().numpy().reshape(-1))

                    # print training/validation statistics
                    valid_running_loss.append(val_loss)
                    valid_running_accuracy.append(f1)
                    valid_running_precision.append(precision)
                    valid_running_recall.append(recall)
                    valid_running_dice.append(iou)

                    # clear variables from memory
                    del inputs, labels, outputs 
                    torch.cuda.empty_cache()


            train_epoch_loss.append(np.mean(train_running_loss))
            valid_epoch_loss.append(np.mean(valid_running_loss))
            valid_epoch_dice.append(np.mean(valid_running_dice))
            valid_epoch_accuracy.append(np.mean(valid_running_accuracy))
            valid_epoch_precision.append(np.mean(valid_running_precision))
            valid_epoch_recall.append(valid_running_recall)
            epoch_list.append(epoch)

            summary_writer.add_scalar("ave_train_loss", train_epoch_loss[-1], epoch)
            summary_writer.add_scalar("ave_valid_loss", valid_epoch_loss[-1], epoch)
            summary_writer.add_scalar("ave_iou", valid_epoch_dice[-1], epoch)
            summary_writer.add_scalar("ave_f1score", valid_epoch_accuracy[-1], epoch)
            summary_writer.add_scalar("ave_precision", valid_epoch_precision[-1], epoch)
            summary_writer.add_scalar("ave_recall", valid_epoch_recall[-1], epoch)

            if epoch > epoch_buffer:
                if valid_epoch_dice[-1]>best_valid_iou:
                    best_valid_iou = valid_epoch_dice[-1]
                    best_valid_epoch = epoch

                    # delete previous checkpoint (s)
                    for ckpt_fp in glob(os.path.join(checkpoints_path, "*.pt.*")):
                        os.remove(ckpt_fp)

                    # save weights
                    torch.save(model.state_dict(), os.path.join(checkpoints_path, f"{args.run_name}_cp-{epoch:04d}).pt"))

            msg ='Epoch: {:04d}, Training Loss: {:2.3f}, Validation Loss: {:2.3f}, \
            Validation precision: {:2.3f}, Validation recall: {:2.3f}, Validation f1 score: {:2.3f}, Validation IoU: {:2.3f},  LR: {:2.6f}  [Time_taken: {:2.3f}s]'.format(                
            epoch, train_epoch_loss, valid_loss,  valid_precision, valid_recall, valid_accuracy, valid_dice, scheduler.get_last_lr()[0], time.time()-epoch_start_time)
            
            # log average lossses
            logger.info(f"{msg}")

            if early_stopping.early_stop:
                logger.info("Early stopping")
                break

    except KeyboardInterrupt:
        logger.warning('Training stopped manually!')


    logger.info(f"Total training time: {(time.time()-epoch_start_time)/60:4.4f} minutues")
    logger.info(f"Best Validation IOU = {best_valid_iou} (at epooch {best_valid_iou})")

    # save train and valid
    results_path = os.path.join(args.save_path, args.run_name, "results")
    os.makedirs(results_path, exist_ok=True)

    train_valid_results_df = pd.DataFrame({'train_loss':[x for x in train_epoch_loss],
    'valid_loss': [x for x in valid_epoch_loss],
    'valid_iou': [x for x in valid_epoch_dice],
    'valid_f1score': [x for x in valid_epoch_accuracy],
    'Valid_precision': [x for x in valid_epoch_precision],
    'Valid_recall': [x for x in valid_epoch_recall]}
    )

    train_valid_results_df.to_csv(os.path.join(results_path,"train_valid.csv"), index_label="epoch", float_format='%.4f')

    # create empty dataframe 
    test_df = pd.DataFrame(columns=['iou', 'f1score', 'precision', 'recall'])

    # create test ds for final evaluation
    logger.info(f"Creating test dataset for evaluating best model......")
    ls_eval_ds = ls_dataset.create_set(batch_size=1, shuffle=False, pin_memory=True, num_workers=4)

    logger.info(f"Loading model from best validation epoch.....")
    model.load_state_dict(torch.load(os.path.join(checkpoints_path, f"{args.run_name}_cp-{best_valid_epochpoch:04d}.pt")))


    model.eval()
    for batch_idx, (inputs, labels, names) in enumerate(ls_eval_ds):
        # load data and move data to GPU's
        inputs = inputs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        # forward-propogation
        outputs = model(inputs) 

        # compute the metrics
        outputs = (outputs >= args.threshold)*1
        iou     =  iou_pytorch(outputs, labels.detach().item())
        f1, precision, recall  = pixel_segementation_evaluation(labels.cpu().detach().numpy().reshape(-1),
        outputs.cpu().detach().numpy().reshape(-1))

        test_df.loc[i] = [iou, f1, precision, recall]

    # save test to disk
    test_df.to_csv(os.path.join(results_path,"best_test_results.csv"), index_label="step", float_format='%.4f')

    logger.info(f'========= DONE ========')







