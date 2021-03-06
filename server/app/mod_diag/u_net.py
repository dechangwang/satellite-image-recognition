import gc
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
from keras.layers import concatenate, Conv2D, Input, MaxPooling2D, UpSampling2D, Cropping2D
from keras.layers.normalization import BatchNormalization
from keras.models import Model
from keras.optimizers import Nadam
from sklearn.model_selection import train_test_split


class U_net(object):
    def hello(self):
        print("U-net")

    def __init__(self, n_split, crop_size, patch_size, get_size, test_file_dir, msk_file_dir="", file_dir=""):
        self.smooth = 1e-12
        self.n_split = n_split
        self.crop_size = crop_size
        self.patch_size = patch_size
        self.edge_size = int((self.crop_size - self.patch_size) / 2)
        self.get_size = get_size
        self.scale_size = self.patch_size * self.n_split
        self.test_file_dir = test_file_dir
        self.msk_file_dir = msk_file_dir
        self.file_dir = file_dir

        self.dic_class = dict()
        self.dic_class['water'] = [48, 93, 254]
        self.dic_class['tree'] = [12, 169, 64]
        self.dic_class['playground'] = [139, 69, 19]
        self.dic_class['road'] = [47, 79, 79]
        self.dic_class['building_yard'] = [255, 255, 255]
        self.dic_class['bare_land'] = [239, 156, 119]
        self.dic_class['general_building'] = [249, 255, 25]
        self.dic_class['countryside'] = [227, 23, 33]
        self.dic_class['factory'] = [48, 254, 254]
        self.dic_class['shadow'] = [255, 1, 255]

    def get_mask(self, image_id, name_class):
        filename = os.path.join(
            self.file_dir, name_class, '{}.tif'.format(image_id))
        msk = tiff.imread(filename)
        msk = msk.astype(np.float32) / 255
        msk = cv2.resize(msk, (self.scale_size, self.scale_size))
        msk_img = np.zeros([self.scale_size, self.scale_size], dtype=np.uint8)
        msk_img[:, :] = msk[:, :, 1]
        msk_img ^= 1
        return msk_img

    def get_image_row(self, image_id, dir_name):
        filename = os.path.join(dir_name, '{}.tif'.format(image_id))
        img = tiff.imread(filename)
        return img

    def get_image(self, image_id):
        filename = os.path.join(
            self.file_dir, 'split-data', '{}.tif'.format(image_id))
        img = tiff.imread(filename)
        img = img.astype(np.float32) / 255
        img_RGB = cv2.resize(img, (self.scale_size, self.scale_size))
        return img_RGB

    def reflect_img(self, img):
        reflect = cv2.copyMakeBorder(img, self.edge_size, self.edge_size, self.edge_size, self.edge_size,
                                     cv2.BORDER_REFLECT)
        return reflect

    def rotate_img(self, img, ang, size):
        rows = size
        cols = size
        M = cv2.getRotationMatrix2D((cols / 2, rows / 2), 90 * ang, 1)
        dst = cv2.warpAffine(img, M, (cols, rows))
        return dst

    def rotate_msk(self, msk, ang):
        return np.rot90(msk, ang)

    def get_patch(self, img_id, name_class, pos=1):
        img_ = []
        msk_ = []
        img = self.get_image(img_id)
        img = self.reflect_img(img)
        mask = self.get_mask(img_id, name_class)
        for i in range(self.n_split):
            for j in range(self.n_split):
                y = mask[self.patch_size * i:self.patch_size * (i + 1), self.patch_size * j:self.patch_size * (j + 1)]
                if ((pos == 1) and (np.sum(y) > 0)) or (pos == 0):
                    x_start = int(self.patch_size * i)
                    x_end = int(self.patch_size * (i + 1) + self.edge_size * 2)
                    y_start = int(self.patch_size * j)
                    y_end = int(self.patch_size * (j + 1) + self.edge_size * 2)
                    x = img[x_start:x_end, y_start:y_end, :]
                    # start rotate y and x
                    rdm = random.uniform(-2, 5)
                    if rdm > 1:
                        ang = rdm // 1
                        x = self.rotate_img(x, ang, self.crop_size)
                        y = self.rotate_msk(y, ang)
                        # print(x.shape)
                        # print(y.shape)

                    img_.append(x)
                    msk_.append(y[:, :, None])

        return img_, msk_

    def get_all_patches(self, name_class, Image_ID, pos=1):
        img_all = []
        msk_all = []
        count = 0
        for img_id in Image_ID:
            img_, msk_ = self.get_patch(img_id, name_class, pos=pos)
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

    def get_normalized_patches(self, name_class, Image_ID):
        img_all, msk_all = self.get_all_patches(name_class, Image_ID)
        #     data = np.load(Dir + '/output/data_pos_%d_%d_class%d.npy' % (Patch_size, N_split, Class_Type))
        img = img_all
        msk = msk_all
        mean = np.mean(img)
        std = np.std(img)
        img = (img - mean) / std
        print(mean, std)
        # print(np.mean(img), np.std(img))
        return img, msk

    def jaccard_coef(self, y_true, y_pred):
        intersection = K.sum(y_true * y_pred, axis=[0, -1, -2])
        sum_ = K.sum(y_true + y_pred, axis=[0, -1, -2])

        jac = (intersection + self.smooth) / (sum_ - intersection + self.smooth)

        return K.mean(jac)

    def jaccard_coef_int(self, y_true, y_pred):
        y_pred_pos = K.round(K.clip(y_pred, 0, 1))

        intersection = K.sum(y_true * y_pred_pos, axis=[0, -1, -2])
        sum_ = K.sum(y_true + y_pred_pos, axis=[0, -1, -2])

        jac = (intersection + self.smooth) / (sum_ - intersection + self.smooth)

        return K.mean(jac)

    def jaccard_coef_loss(self, y_true, y_pred):
        return -K.log(self.jaccard_coef(y_true, y_pred)) + binary_crossentropy(y_pred, y_true)

    # In predicting testing dataset, need to use the same mean and std in preprocessing training data
    def post_normalize_image(self, img, mean=0.338318, std=0.189734):
        img = (img - mean) / std
        return img

    def get_unet1(self):
        inputs = Input((self.crop_size, self.crop_size, 3))
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
        crop9 = Cropping2D(cropping=((self.edge_size, self.edge_size), (self.edge_size, self.edge_size)))(conv9)
        conv9 = BatchNormalization(axis=1)(crop9)
        conv9 = keras.layers.advanced_activations.ELU()(conv9)

        conv10 = Conv2D(1, (1, 1), activation='sigmoid')(conv9)

        model = Model(inputs=inputs, outputs=conv10)
        model.compile(optimizer=Nadam(lr=1e-3), loss=self.jaccard_coef_loss,
                      metrics=['binary_crossentropy', self.jaccard_coef_int])
        return model

    def get_image_without_msk(self, input_image):
        img = input_image
        img = img.astype(np.float32) / 255
        img_RGB = cv2.resize(img, (self.scale_size, self.scale_size))
        return img_RGB

    def get_model_by_name(self, model_name):
        if model_name == "unet2":
            return self.get_unet2()
        elif model_name == "unet1":
            return self.get_unet1()
        else:
            return self.get_unet0()

    def train(self, name_class, data_imageID_file, model_name, epochs=100):
        train_img = pd.read_csv(data_imageID_file)
        all_image_id = sorted(train_img.ImageId.unique())
        all_len = len(all_image_id)
        loop_time = all_len // self.get_size
        last_weight = ''
        loop_i = 0
        # print(name_class)
        for i in range(loop_time):
            Image_ID = random.sample(all_image_id, self.get_size)
            all_image_id = [Image_ID2 for Image_ID2 in all_image_id if Image_ID2 not in Image_ID]
            img, msk = self.get_normalized_patches(name_class, Image_ID)
            x_trn, x_val, y_trn, y_val = train_test_split(img, msk, test_size=0.2, random_state=42)
            y_trn = y_trn[:, :, :, None]
            y_val = y_val[:, :, :, None]
            model = self.get_model_by_name(model_name)
            if i != 0:
                # print("loaded")
                model.load_weights(last_weight)

            check_point_file_name = str(loop_i) + name_class + '.hdf5'
            model_checkpoint = ModelCheckpoint(check_point_file_name, monitor='val_jaccard_coef_int',
                                               save_best_only=True,
                                               mode='max')
            model.fit(x_trn, y_trn, batch_size=16, epochs=epochs, verbose=1, shuffle=True,
                      callbacks=[model_checkpoint],
                      validation_data=(x_val, y_val))
            last_weight = check_point_file_name
            loop_i += 1
            del x_trn, x_val, y_trn, y_val, model
            gc.collect()

        img_last = all_len - loop_time * self.get_size
        if img_last > 0:
            Image_ID = random.sample(all_image_id, img_last)

            img, msk = self.get_normalized_patches(name_class, Image_ID)
            x_trn, x_val, y_trn, y_val = train_test_split(img, msk, test_size=0.2, random_state=42)
            y_trn = y_trn[:, :, :, None]
            y_val = y_val[:, :, :, None]

            model = self.get_model_by_name(model_name)
            if loop_i != 0:
                # print("loaded")
                model.load_weights(last_weight)
            check_point_file_name = str(loop_i) + name_class + '.hdf5'
            model_checkpoint = ModelCheckpoint(check_point_file_name, monitor='val_jaccard_coef_int',
                                               save_best_only=True,
                                               mode='max')
            model.fit(x_trn, y_trn, batch_size=16, epochs=epochs, verbose=1, shuffle=True, callbacks=[model_checkpoint],
                      validation_data=(x_val, y_val))

    def predict_id(self, img, model, th):
        prd = np.zeros((self.patch_size * self.n_split, self.patch_size * self.n_split, 1)).astype(np.float32)
        for i in range(self.n_split):
            for j in range(self.n_split):
                x = img[self.patch_size * i:self.patch_size * (i + 1), self.patch_size * j:self.patch_size * (j + 1), :]
                x = self.reflect_img(x)
                tmp = model.predict(x[None, :, :, :], batch_size=4)
                prd[self.patch_size * i:self.patch_size * (i + 1), self.patch_size * j:self.patch_size * (j + 1)] = tmp
        prd_result = prd > th
        # dst = morphology.remove_small_objects(prd_result, min_size=300, connectivity=10)
        return prd_result

    def get_mask_by_name(self, class_name):
        if class_name == 'road':
            return road_msk
        elif class_name == 'factory':
            return factory_msk
        elif class_name == 'general_building':
            return build_msk
        elif class_name == 'shadow':
            return shadow_msk
        elif class_name == 'countryside':
            return countryside_msk
        elif class_name == 'water':
            return water_msk
        elif class_name == 'bare_land':
            return bare_land_msk
        elif class_name == 'building_yard':
            return building_yard_msk
        elif class_name == 'playground':
            return playground_msk
        elif class_name == 'tree':
            return tree_msk

    def draw_mask(self, class_names, width, height):

        for c in class_names:
            msk = self.get_mask_by_name(c)
            if msk is not None and msk[width][height]:
                return self.dic_class[c]
            else:
                continue
        return False

    def predict_target_classes(self, set_classes, input_image):
        global road_msk, factory_msk, build_msk, shadow_msk, countryside_msk, water_msk, \
            bare_land_msk, building_yard_msk, playground_msk, tree_msk
        road_msk = None
        factory_msk = None
        build_msk = None
        shadow_msk = None
        countryside_msk = None
        water_msk = None
        bare_land_msk = None
        building_yard_msk = None
        playground_msk = None
        tree_msk = None

        img = self.get_image_without_msk(input_image)
        img = self.post_normalize_image(img)

        order_list = list()
        class_list = list()

        if set_classes.get("general_building") is not None:
            build_msk = self.predict_id(img=img, model=set_classes.get("general_building").model, th=0.5)
            build_msk = build_msk[:, :, 0]
            order_list.append(set_classes.get("general_building").order)
            class_list.append("general_building")

        if set_classes.get("road") is not None:
            road_msk = self.predict_id(img=img, model=set_classes.get("road").model, th=0.5)
            road_msk = road_msk[:, :, 0]
            order_list.append(set_classes.get("road").order)
            class_list.append("road")

        if set_classes.get("factory") is not None:
            factory_msk = self.predict_id(img=img, model=set_classes.get("factory").model, th=0.5)
            factory_msk = factory_msk[:, :, 0]
            order_list.append(set_classes.get("factory").order)
            class_list.append("factory")
        if set_classes.get("countryside") is not None:
            countryside_msk = self.predict_id(img=img, model=set_classes.get("countryside").model, th=0.5)
            countryside_msk = countryside_msk[:, :, 0]
            order_list.append(set_classes.get("countryside").order)
            class_list.append("countryside")
        if set_classes.get("shadow") is not None:
            shadow_msk = self.predict_id(img=img, model=set_classes.get("shadow").model, th=0.5)
            shadow_msk = shadow_msk[:, :, 0]
            order_list.append(set_classes.get("shadow").order)
            class_list.append("shadow")
        if set_classes.get("water") is not None:
            water_msk = self.predict_id(img=img, model=set_classes.get("water").model, th=0.5)
            water_msk = water_msk[:, :, 0]
            order_list.append(set_classes.get("water").order)
            class_list.append("water")
        if set_classes.get("bare_land") is not None:
            bare_land_msk = self.predict_id(img=img, model=set_classes.get("bare_land").model, th=0.5)
            bare_land_msk = bare_land_msk[:, :, 0]
            order_list.append(set_classes.get("bare_land").order)
            class_list.append("bare_land")
        if set_classes.get("building_yard") is not None:
            building_yard_msk = self.predict_id(img=img, model=set_classes.get("building_yard").model, th=0.5)
            building_yard_msk = building_yard_msk[:, :, 0]
            order_list.append(set_classes.get("building_yard").order)
            class_list.append("building_yard")
        if set_classes.get("playground") is not None:
            playground_msk = self.predict_id(img=img, model=set_classes.get("playground").model, th=0.5)
            playground_msk = playground_msk[:, :, 0]
            order_list.append(set_classes.get("playground").order)
            class_list.append("playground")
        if set_classes.get("tree") is not None:
            tree_msk = self.predict_id(img=img, model=set_classes.get("tree").model, th=0.5)
            tree_msk = tree_msk[:, :, 0]
            order_list.append(set_classes.get("tree").order)
            class_list.append("tree")

        ordered_class = [x for _, x in sorted(zip(order_list, class_list))]

        row_img = input_image
        row_img = cv2.resize(row_img, (self.scale_size, self.scale_size))
        merge_msk = np.copy(row_img)
        width = self.scale_size
        height = self.scale_size
        # ordered_class = ordered_class.reverse()
        # print(ordered_class)
        for i in range(width):
            for j in range(height):
                tmp = self.draw_mask(ordered_class, i, j)
                if tmp:
                    merge_msk[i][j] = tmp
        # print("finished")
        # msk_file_name = self.msk_file_dir + "/" + img_id + ".tif"
        # tiff.imsave(msk_file_name, merge_msk)
        return merge_msk
