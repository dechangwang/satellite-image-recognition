import os
import random

import cv2
import keras
import numpy as np
import pandas as pd
import tifffile as tiff
from keras import backend as K
from keras.backend import binary_crossentropy
from keras.callbacks import ModelCheckpoint
from keras.layers import concatenate, Conv2D, Input, MaxPooling2D, UpSampling2D, Cropping2D, Convolution2D, Flatten, \
    Dense, Activation, Dropout
from keras.layers.normalization import BatchNormalization
from keras.models import Model, Sequential
from keras.optimizers import Nadam
from keras.utils import np_utils
from sklearn.model_selection import train_test_split

n_class = 10
Dir = '/home/yokoyang/PycharmProjects/untitled/896_biaozhu'

train_img = pd.read_csv(Dir + '/data_imageID.csv')

Image_ID = sorted(train_img.ImageId.unique())

N_split = 4

Patch_size = 192
crop_size = 224
edge_size = int((crop_size - Patch_size) / 2)
Class_Type = 1

Scale_Size = Patch_size * N_split
get_size = 231
smooth = 1e-12


def get_mask(image_id):
    filename = os.path.join(
        Dir, 'mix_all', '{}.npy'.format(image_id))
    msk = np.load(filename)
    msk = np_utils.to_categorical(msk, n_class)
    return msk


def get_image(image_id):
    filename = os.path.join(
        Dir, 'split-data', '{}.tif'.format(image_id))
    img = tiff.imread(filename)
    img = img.astype(np.float32) / 255
    img_RGB = cv2.resize(img, (Scale_Size, Scale_Size))
    return img_RGB


def reflect_img(img):
    reflect = cv2.copyMakeBorder(img, int(edge_size), int(edge_size), int(edge_size), int(edge_size),
                                 cv2.BORDER_REFLECT)
    return reflect


def rotate_img(img, ang, size):
    rows = size
    cols = size
    M = cv2.getRotationMatrix2D((cols / 2, rows / 2), 90 * ang, 1)
    dst = cv2.warpAffine(img, M, (cols, rows))
    return dst


def rotate_msk(msk, ang):
    return np.rot90(msk, ang)


def get_patch(img_id, pos=1):
    print(img_id)
    img_ = []
    msk_ = []
    img = get_image(img_id)
    img = reflect_img(img)
    mask = get_mask(img_id)
    for i in range(N_split):
        for j in range(N_split):
            y = mask[Patch_size * i:Patch_size * (i + 1), Patch_size * j:Patch_size * (j + 1)]
            if ((pos == 1) and (np.sum(y) > 0)) or (pos == 0):
                x_start = int(Patch_size * i)
                x_end = int(Patch_size * (i + 1) + edge_size * 2)
                y_start = int(Patch_size * j)
                y_end = int(Patch_size * (j + 1) + edge_size * 2)
                x = img[x_start:x_end, y_start:y_end, :]
                # start rotate y and x
                rdm = random.uniform(-2, 5)
                if rdm > 1:
                    ang = rdm // 1
                    x = rotate_img(x, ang, crop_size)
                    y = rotate_msk(y, ang)

                img_.append(x)
                msk_.append(y)

    return img_, msk_


def get_all_patches(pos=1):
    img_all = []
    msk_all = []
    count = 0
    for img_id in Image_ID:
        img_, msk_ = get_patch(img_id, pos=pos)
        if len(msk_) > 0:
            count = count + 1
            if count == 1:
                img_all = img_
                msk_all = msk_
            else:
                img_all = np.concatenate((img_all, img_), axis=0)
                msk_all = np.concatenate((msk_all, msk_), axis=0)

    # if pos == 1:
    #     np.save(Dir + '/output/data_pos_%d_%d_class%d' % (crop_size, N_split, Class_Type), img_all)
    #
    # else:
    #     np.save(Dir + '/output/data_%d_%d_class%d' % (crop_size, N_split, Class_Type), img_all)

    return img_all, msk_all[:, :, :, 0]


def get_normalized_patches():
    img_all, msk_all = get_all_patches()
    #     data = np.load(Dir + '/output/data_pos_%d_%d_class%d.npy' % (Patch_size, N_split, Class_Type))
    img = img_all
    msk = msk_all
    mean = np.mean(img)
    std = np.std(img)
    img = (img - mean) / std
    print(mean, std)
    # print(np.mean(img), np.std(img))
    return img, msk


def jaccard_coef(y_true, y_pred):
    intersection = K.sum(y_true * y_pred, axis=[0, -1, -2])
    sum_ = K.sum(y_true + y_pred, axis=[0, -1, -2])

    jac = (intersection + smooth) / (sum_ - intersection + smooth)

    return K.mean(jac)


def jaccard_coef_int(y_true, y_pred):
    y_pred_pos = K.round(K.clip(y_pred, 0, 1))

    intersection = K.sum(y_true * y_pred_pos, axis=[0, -1, -2])
    sum_ = K.sum(y_true + y_pred_pos, axis=[0, -1, -2])

    jac = (intersection + smooth) / (sum_ - intersection + smooth)

    return K.mean(jac)


def jaccard_coef_loss(y_true, y_pred):
    return -K.log(jaccard_coef(y_true, y_pred)) + binary_crossentropy(y_pred, y_true)


def post_normalize_image(img, mean=0.338318, std=0.189734):
    img = (img - mean) / std
    return img


def cnn_model():
    model = Sequential()
    model.add(Convolution2D(32, 3, 3, padding='same', input_shape=(crop_size, crop_size, 3),
                            kernel_initializer='he_uniform', activation='relu'))
    model.add(Flatten())

    model.add(Dense(512))
    model.add(Activation('relu'))
    model.add(Dropout(0.2))

    model.add(Dense(512))
    model.add(Activation('relu'))
    model.add(Dropout(0.2))

    model.add(Dense(512))
    model.add(Activation('relu'))
    model.add(Dropout(0.2))

    return model


def get_unet1():
    inputs = Input((crop_size, crop_size, 3))
    conv1 = Conv2D(32, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(inputs)
    conv1 = BatchNormalization(axis=1)(conv1)
    conv1 = keras.layers.advanced_activations.ELU()(conv1)
    conv1 = Conv2D(32, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv1)
    conv1 = BatchNormalization(axis=1)(conv1)
    conv1 = keras.layers.advanced_activations.ELU()(conv1)
    pool1 = MaxPooling2D(pool_size=(2, 2))(conv1)

    conv2 = Conv2D(64, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(pool1)
    conv2 = BatchNormalization(axis=1)(conv2)
    conv2 = keras.layers.advanced_activations.ELU()(conv2)
    conv2 = Conv2D(64, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv2)
    conv2 = BatchNormalization(axis=1)(conv2)
    conv2 = keras.layers.advanced_activations.ELU()(conv2)
    pool2 = MaxPooling2D(pool_size=(2, 2))(conv2)

    conv3 = Conv2D(128, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(pool2)
    conv3 = BatchNormalization(axis=1)(conv3)
    conv3 = keras.layers.advanced_activations.ELU()(conv3)
    conv3 = Conv2D(128, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv3)
    conv3 = BatchNormalization(axis=1)(conv3)
    conv3 = keras.layers.advanced_activations.ELU()(conv3)
    pool3 = MaxPooling2D(pool_size=(2, 2))(conv3)

    conv4 = Conv2D(256, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(pool3)
    conv4 = BatchNormalization(axis=1)(conv4)
    conv4 = keras.layers.advanced_activations.ELU()(conv4)
    conv4 = Conv2D(256, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv4)
    conv4 = BatchNormalization(axis=1)(conv4)
    conv4 = keras.layers.advanced_activations.ELU()(conv4)
    pool4 = MaxPooling2D(pool_size=(2, 2))(conv4)

    conv5 = Conv2D(512, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(pool4)
    conv5 = BatchNormalization(axis=1)(conv5)
    conv5 = keras.layers.advanced_activations.ELU()(conv5)
    conv5 = Conv2D(512, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv5)
    conv5 = BatchNormalization(axis=1)(conv5)
    conv5 = keras.layers.advanced_activations.ELU()(conv5)

    up6 = Conv2D(256, (2, 2), activation='relu', padding='same', kernel_initializer='he_uniform')(
        UpSampling2D(size=(2, 2))(conv5))
    merge6 = concatenate([conv4, up6], axis=3)
    conv6 = Conv2D(256, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(merge6)
    conv6 = BatchNormalization(axis=1)(conv6)
    conv6 = keras.layers.advanced_activations.ELU()(conv6)
    conv6 = Conv2D(256, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv6)
    conv6 = BatchNormalization(axis=1)(conv6)
    conv6 = keras.layers.advanced_activations.ELU()(conv6)

    up7 = Conv2D(128, (2, 2), activation='relu', padding='same', kernel_initializer='he_uniform')(
        UpSampling2D(size=(2, 2))(conv6))
    merge7 = concatenate([conv3, up7], axis=3)
    conv7 = Conv2D(128, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(merge7)
    conv7 = BatchNormalization(axis=1)(conv7)
    conv7 = keras.layers.advanced_activations.ELU()(conv7)
    conv7 = Conv2D(128, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv7)
    conv7 = BatchNormalization(axis=1)(conv7)
    conv7 = keras.layers.advanced_activations.ELU()(conv7)

    up8 = Conv2D(64, (2, 2), activation='relu', padding='same', kernel_initializer='he_uniform')(
        UpSampling2D(size=(2, 2))(conv7))
    merge8 = concatenate([conv2, up8], axis=3)

    conv8 = Conv2D(64, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(merge8)
    conv8 = BatchNormalization(axis=1)(conv8)
    conv8 = keras.layers.advanced_activations.ELU()(conv8)
    conv8 = Conv2D(64, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv8)
    conv8 = BatchNormalization(axis=1)(conv8)
    conv8 = keras.layers.advanced_activations.ELU()(conv8)

    up9 = Conv2D(32, (2, 2), activation='relu', padding='same', kernel_initializer='he_uniform')(
        UpSampling2D(size=(2, 2))(conv8))
    merge9 = concatenate([conv1, up9], axis=3)

    conv9 = Conv2D(32, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(merge9)
    conv9 = BatchNormalization(axis=1)(conv9)
    conv9 = keras.layers.advanced_activations.ELU()(conv9)
    conv9 = Conv2D(32, (3, 3), activation='relu', padding='same', kernel_initializer='he_uniform')(conv9)
    crop9 = Cropping2D(cropping=((edge_size, edge_size), (edge_size, edge_size)))(conv9)
    conv9 = BatchNormalization(axis=1)(crop9)
    conv9 = keras.layers.advanced_activations.ELU()(conv9)

    conv10 = Conv2D(n_class, (1, 1), activation='softmax')(conv9)

    model = Model(inputs=inputs, outputs=conv10)
    model.compile(optimizer=Nadam(lr=1e-3), loss=jaccard_coef_loss, metrics=['binary_crossentropy', jaccard_coef_int])
    return model


all_Image_ID = sorted(train_img.ImageId.unique())
all_len = len(all_Image_ID)
loop_time = all_len // get_size
last_weight = ''
loop_i = 0
for i in range(loop_time):
    Image_ID = random.sample(all_Image_ID, get_size)
    all_Image_ID = [Image_ID2 for Image_ID2 in all_Image_ID if Image_ID2 not in Image_ID]
    print("loading image")
    img, msk = get_normalized_patches()
    print("start")
    x_trn, x_val, y_trn, y_val = train_test_split(img, msk, test_size=0.2, random_state=42)
    y_trn = y_trn[:, :, :, None]
    y_val = y_val[:, :, :, None]

    model = get_unet1()
    if i != 0:
        print("loaded")
        model.load_weights(last_weight)
    check_point_file_name = 'all.hdf5'
    model_checkpoint = ModelCheckpoint(check_point_file_name, monitor='val_jaccard_coef_int', save_best_only=True,
                                       mode='max')
    model.fit(x_trn, y_trn, batch_size=16, epochs=100, verbose=1, shuffle=True, callbacks=[model_checkpoint],
              validation_data=(x_val, y_val))
    last_weight = check_point_file_name
    loop_i += 1
    del x_trn, x_val, y_trn, y_val, model

img_last = all_len - loop_time * get_size
print(img_last)
