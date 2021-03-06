import os

import pandas as pd

# Dir = "/home/yokoyang/PycharmProjects/untitled/v-shanghai"
Dir = "/home/yokoyang/PycharmProjects/untitled/new_data/mask"


def get_files_name(file_dir):
    L = []
    for root, dirs, files in os.walk(file_dir):
        for file in files:
            if os.path.splitext(file)[1] == '.tif':
                L.append(os.path.splitext(file)[0])
    return L


def image2csv(dir_name, csv_name):
    L = get_files_name(dir_name)
    df = pd.DataFrame()
    df['ImageId'] = L
    df.to_csv(Dir + "/" + csv_name, index=False, header=True)


# image2csv(Dir + "/" + "general_building", "mask_data_imageID.csv")
image2csv(Dir, "data_imageID.csv")
