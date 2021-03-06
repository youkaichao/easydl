import os
import numpy as np
import skimage.io as io
import skimage.transform as T
import tensorpack
import time
import random
from scipy.misc import imread, imresize
import tensorlayer as tl
import cPickle
from wheel import *

class CustomDataLoader(object):
    '''
    dataloader to load datapoints of dataset and merge them as a mini-batch
    
    ****usage****
    ==========train mode=========
    ds = TestDataset(is_train=True)
    dl = CustomDataLoader(dataset=ds, batch_size=6, num_threads=2)
    for (x, y) in dl.generator():
        print((x, y, x.shape, y.shape))
    for (x, y) in dl.generator():
        print((x, y, x.shape, y.shape))
    ==========the data is random, and different in each call of dl.generator()==============
    
    ===========test mode================
    ds = TestDataset(is_train=False)

    dl = CustomDataLoader(dataset=ds, batch_size=6, num_threads=2)
    for (x, y) in dl.generator():
        print((x, y, x.shape, y.shape))
    assert x.shape[0] == ds.N % dl.batch_size
    for (x, y) in dl.generator():
        print((x, y, x.shape, y.shape))
    =======the data has a specific order, each call of dl.generator() returns the same data sequence===============
    '''
    def __init__(self, dataset, batch_size, num_threads=8,remainder=None):
        '''
        args:
        dataset: subclass of tensorpack.dataflow.RNGDataFlow
        batch_size:(int)
        num_threads:(int) numbers of threads to use (training mode is inferred according to dataset, 
            if not training, this argument is ignored)
            
        **********
        useful only in test mode, and you'd better not set this arg cause it can be inferred from attributes of dataset arg
        **********
        remainder: (bool) whether to use data that can't form a whole batch, like you have 100 data, batchsize is 3, this arg indicates
            whether to use the remaining 1 data 
        '''
        self.ds0 = dataset
        self.batch_size = batch_size
        self.num_threads = num_threads
        
        if not remainder:
            try:
                is_train = self.ds0.is_train
                remainder = False if is_train else True # if is_train, there is no need to set reminder 
            except Exception as e:
                # self.ds0 maybe doesn't have is_train attribute, then it has no test mode, set remainder = False
                remainder = False
        
        # use_list=False, for each in data point, add a batch dimension (return in numpy array)
        self.ds1 = tensorpack.dataflow.BatchData(self.ds0, self.batch_size,remainder=remainder, use_list=False,) 
        
        # use 1 thread in test to avoid randomness (test should be deterministic)
        self.ds2 = tensorpack.dataflow.PrefetchDataZMQ(self.ds1, nr_proc=self.num_threads if not remainder else 1)
        
        # required by tensorlayer package
        self.ds2.reset_state()
    
    def generator(self):
        '''
        if self.ds0.get_data() returns N elements, then this function returns a generator, which yields N elements
        '''
        return self.ds2.get_data()
    

class TestDataset(tensorpack.dataflow.RNGDataFlow):
    '''
    simple test dataset to store N data, ith data is [i, i+1], [2i+1] where 0 <= i < N

    ****usage****

    for (x, y) in TestDataset(is_train=True).get_data():
        print((x, y))
    for (x, y) in TestDataset(is_train=False).get_data():
        print((x, y))
    '''
    def __init__(self,is_train=True, N=100):
        '''
        args:
        N:(int)
        is_train:(bool) if is_train, return data randomly. else, return data in test mode(i.e., generate samples in specific order)
        '''
        self.is_train = is_train
        self.N = N
        
    def size(self):
        '''
        the result of this function is used to determine the size of one batch
        '''
        return self.N
    
    def get_data(self):
        '''
        this function should yield a tuple, each element in the tuple should be np array
        '''
        number = self.N
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            x = np.asarray([id, id+1])
            y = np.asarray([2 * id + 1])
            yield x, y

class FileListDataset(tensorpack.dataflow.RNGDataFlow):
    '''
    useful for complicated dataset like dataset in open set problem
    '''
    def __init__(self, list_path, path_prefix='',is_train=True,imsize=224, n_class=None, label_transform=None, skip_pred=None):
        '''
        args:
        
        list_path :(str) absolute path of image list file (which contains (path, label_id) in each line) *avoid space in path!*
        path_prefix :(str) prefix to add to each line in image list to get the absolute path of image, 
            esp, you should set path_prefix if file path in image list file is relative path
        is_train:(bool)
        imsize:(int) the size of image to be returned(original image will be loaded and resized to this size)
        n_class:(int)total number of classes. this arg determines the dimension of the returned label
        label_transform:(callable, (int)->int) transform the label in image list file to a specific label. useful if the image comes from
            a larger dataset where it has 1000 label, and you only want to use 100 of them which is [200, 300), 
            then you can set n_class=100 and label_transform=lambda x : x - 200
        skip_pred:(callable, (int)->bool) unary predicate, skip the data when the skip_pred returns true. used to filter dataset
        '''
        self.list_path = list_path
        self.path_prefix = path_prefix
        self.is_train = is_train
        self.imsize=imsize
        self.label_transform = label_transform
        self.skip_pred = skip_pred or (lambda x : False)
        
        with open(self.list_path, 'r') as f:
            data = [[line.split()[0], line.split()[1]] for line in f.readlines() if line.strip()] # avoid empty lines
            self.files = [join_path(self.path_prefix, x[0]) for x in data]
            try:
                self.labels = [int(x[1]) for x in data]
            except ValueError as e:
                print('invalid label number, maybe there is space in image path?')
                raise e
            
            tmp = [[file, label] for file, label in zip(self.files, self.labels) if not self.skip_pred(label)]
            self.files = [x[0] for x in tmp]
            self.labels = [x[1] for x in tmp]
                
        self.n_class = n_class if n_class else max(self.labels) + 1 # if n_class is not set, try to infer from labels in file list
        
    def size(self):
        return len(self.files)
    
    def get_data(self):
        number = len(self.files)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            file = self.files[id]
            label = self.labels[id]
            if self.label_transform:
                label = self.label_transform(label)

            # create one-hot label
            tmp = np.zeros((self.n_class,), dtype=np.float32)
            tmp[label] = 1.0
            im = imread(file, mode='RGB')
            # resize to 256 and crop 224, then remize to required size
            im = imresize(im, size=(256, 256))
            im = tl.prepro.crop(im, 224, 224, is_random=self.is_train)
            im = imresize(im, (self.imsize, self.imsize))
            yield im,tmp
    
    
class MultiFileListDataset(tensorpack.dataflow.RNGDataFlow):
    '''
    combine multi file lists
    '''
    def __init__(self, list_paths, path_prefixes='',list_repeats = None, is_train=True,imsize=224, n_class=None, label_transforms=None):
        '''
        args:
        
        list_paths :(list of str) absolute path of image list files (which contains (path, label_id) in each line) *avoid space in path!*
        path_prefixes :(str or list of str) prefix to add to each line in image list to get the absolute path of image, 
            esp, you should set path_prefix if file path in image list file is relative path
        list_repeats : (list of number) numbers each file list will repeat (i.e., the probability density of sampling) 
        is_train:(bool)
        imsize:(int) the size of image to be returned(original image will be loaded and resized to this size)
        n_class:(int)total number of classes. this arg determines the dimension of the returned label
        label_transforms:(list of callable, (int)->int) transform the label in image list file to a specific label. useful if the image comes from
            a larger dataset where it has 1000 label, and you only want to use 100 of them which is [200, 300), 
            then you can set n_class=100 and label_transform=lambda x : x - 200
        '''
        self.list_paths = list_paths
        self.path_prefixes = [path_prefixes for path in self.list_paths] if isinstance(path_prefixes, str) else path_prefixes
        self.list_repeats = list_repeats or [1 for path in self.list_paths]
        assert len(self.list_repeats) == len(self.path_prefixes)
        self.is_train = is_train
        self.imsize=imsize
        self.label_transforms = label_transforms or [(lambda x : x) for path in self.list_paths]
        
        self.files = []
        self.labels = []
        self.weights = []
        for list_path, path_prefix, list_repeat, label_transform in zip(self.list_paths, self.path_prefixes, self.list_repeats, self.label_transforms):
            with open(list_path, 'r') as f:
                data = [[line.split()[0], line.split()[1]] for line in f.readlines() if line.strip()] # avoid empty lines
                self.files += [join_path(path_prefix, x[0]) for x in data]
                self.weights += [list_repeat for x in data]
                try:
                    self.labels += [label_transform(int(x[1])) for x in data] 
                except ValueError as e:
                    print('invalid label number, maybe there is space in image path?')
                    raise e
        self.weights = np.asarray(self.weights, dtype=np.float)
        self.weights = self.weights / np.sum(self.weights) # make it a distribution
                
        self.n_class = n_class if n_class else max(self.labels) + 1 # if n_class is not set, try to infer from labels in file list
        
    def size(self):
        return len(self.files)
    
    def get_data(self):
        number = len(self.files)
        numbers = list(range(number))
        for _ in range(number):
            id = np.random.choice(numbers, p=self.weights) if self.is_train else _
            file = self.files[id]
            label = self.labels[id]
            # create one-hot label
            tmp = np.zeros((self.n_class,), dtype=np.float32)
            tmp[label] = 1.0
            im = imread(file, mode='RGB')
            # resize to 256 and crop 224, then remize to required size
            im = imresize(im, size=(256, 256))
            im = tl.prepro.crop(im, 224, 224, is_random=self.is_train)
            im = imresize(im, (self.imsize, self.imsize))
            yield im,tmp
    
import warnings
# disable warning of imread
warnings.filterwarnings('ignore', message='.*', category=DeprecationWarning)

class UnLabeledImageDataset(tensorpack.dataflow.RNGDataFlow):
    '''
    applies to image dataset in one directory without labels for unsupervised learning, like getchu, celeba etc
    there is no test mode in unsupervised learning
    '''
    def __init__(self, root_dir,imsize=128):
        self.root_dir = root_dir
        self.imsize = imsize

        self.files = sum([[os.path.join(path, file) for file in files] for path, dirs, files in os.walk(self.root_dir) if files], [])

    def size(self):
        return len(self.files)
    
    def get_data(self):
        # shuffle and yield data
        random.shuffle(self.files)
        for file in self.files:
            im = imread(file, mode='RGB')
            im = imresize(im, (self.imsize, self.imsize))
            yield (im,)

class ImageFolderDataset(tensorpack.dataflow.RNGDataFlow):
    '''
    dataset for specific directory hierachy:
    root_dir
        class1
            file1
            file2
            ...
        class2
            file1
            file2
            ...
        ...
            
    '''
    def __init__(self, root_dir,is_train=True,imsize=224):
        self.root_dir = root_dir
        self.files = sum([[os.path.join(path, file) for file in files] for path, dirs, files in os.walk(self.root_dir) if files], [])
        self.labels = [file.split(os.sep)[-2] for file in self.files]
        self.classes = sorted(list(set(self.labels)))
        self.NameToId = {x : i for (i, x) in enumerate(self.classes)}
        self.IdToName = {i : x for (i, x) in enumerate(self.classes)}

        self.is_train = is_train
        self.imsize=imsize
        
    def size(self):
        return len(self.files)
    
    def get_data(self):
        number = len(self.files)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            file = self.files[id]
            label = self.NameToId[self.labels[id]]
            tmp = np.zeros((len(self.classes),), dtype=np.float32)
            tmp[label] = 1.0
            im = imread(file, mode='RGB')
            im = imresize(im, size=(256, 256))
            im = tl.prepro.crop(im, 224, 224, is_random=self.is_train)
            im = imresize(im, (self.imsize, self.imsize))
            yield im,tmp

class OfficeHomeDatasetGetter:
    '''
    Office-Home dataset, see http://hemanthdv.org/OfficeHome-Dataset/ for details
    this dataset has 4 domains, each domain is organized in an ImageFolder way, so we need to create a dataset getter
    **the original dataset has a folder named "Real World", which has a space in path, try to rename it to Real_World**
    
    =======usage========
    ds = OfficeHomeDatasetGetter(root_dir=somewhere, id=OfficeHomeDatasetGetter.Art, is_train=, imsize=)()
    =======then use ds like an ImageFolderDataset
    '''
    Art = 0
    Clipart = 1
    Product = 2
    Real_World = 3
    
    def __init__(self, root_dir=os.path.join(getHomePath(), 'data/Office_Home/'), id=0, is_train=True,imsize=224):
        root_dir = root_dir
        names = ['Art', 'Clipart', 'Product', 'Real_World']
        name = names[id]
        root_dir = os.path.join(root_dir, name)
        self.ds = ImageFolderDataset(root_dir=root_dir, is_train=is_train, imsize=imsize)
    def __call__(self):
        return self.ds
    
class OfficeDatasetGetter:
    '''
    office dataset, see https://people.eecs.berkeley.edu/~jhoffman/domainadapt/#datasets_code for details
    download link: https://drive.google.com/open?id=0B4IapRTv9pJ1WGZVd1VDMmhwdlE
    typically, create a folder named office, and download & extract the images under office folder
    so the hierachy should looks like:
    root_dir
        domain_adaptation_images
            amazon
            dslr
            webcam
            
    =======usage========
    ds = OfficeDatasetGetter(root_dir=somewhere, id=OfficeHomeDatasetGetter.Art, is_train=, imsize=)()
    =======then use ds like an ImageFolderDataset
    '''
    amazon = 0
    dslr = 1
    webcam = 2
    
    def __init__(self, root_dir=os.path.join(getHomePath(), 'data/office/'), id=0, is_train=True,imsize=224):
        root_dir = root_dir
        names = ['amazon', 'dslr', 'webcam']
        name = names[id]
        root_dir = os.path.join(root_dir, 'domain_adaptation_images', name, 'images')
        self.ds = ImageFolderDataset(root_dir=root_dir, is_train=is_train, imsize=imsize)
    def __call__(self):
        return self.ds

class OfficeDataset(tensorpack.dataflow.RNGDataFlow):
    '''
    this is kept for compatibility(some old code use it)
    '''
    amazon = 0
    dslr = 1
    webcam = 2
    def __init__(self, root_dir=os.path.join(getHomePath(), 'data/office/'), id=0, is_train=True,imsize=224):
        self.root_dir = root_dir
        names = ['amazon', 'dslr', 'webcam']
        name = names[id]
        file = os.path.join(self.root_dir, '%s_list.txt'%name)
        with open(file) as f:
            data = [line.strip().split(' ') for line in f]
            self.files = [d[0] for d in data]
            self.labels = [int(d[1]) for d in data]

        self.is_train = is_train
        self.imsize=imsize
    def size(self):
        return len(self.files)
    
    def get_data(self):
        number = len(self.files)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            file = self.files[id]
            label = self.labels[id]
            tmp = np.zeros((31,), dtype=np.float32)
            tmp[label] = 1.0
            im = imread(os.path.join(self.root_dir, file), mode='RGB')
            im = imresize(im, size=(256, 256))
            im = tl.prepro.crop(im, 224, 224, is_random=self.is_train)
            im = imresize(im, (self.imsize, self.imsize))
            yield im,tmp
            
from tensorflow.examples.tutorials.mnist import input_data

class MNISTDataset(tensorpack.dataflow.RNGDataFlow):
    def __init__(self, root_dir=os.path.join(getHomePath(), 'code/MNIST_data/'), is_train=True):
        self.mnist = input_data.read_data_sets(train_dir=root_dir, one_hot=True)
        self.is_train = is_train
        self.current_ds = self.mnist.train if self.is_train else self.mnist.test
    def size(self):
        return len(self.current_ds.images)
    def get_data(self):
        number = len(self.current_ds.images)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            yield self.current_ds.images[id].reshape((28, 28, 1)), self.current_ds.labels[id]

    
class CifarDataset(tensorpack.dataflow.RNGDataFlow):
    def __init__(self, root_dir=os.path.join(getHomePath(), 'code/'), is_train=True):
        self.x_train, self.y_train, self.x_test, self.y_test = tl.files.load_cifar10_dataset(shape=(-1, 32, 32, 3), path=root_dir)
        CLASS = 10
        y = np.zeros(shape=(len(self.y_train), CLASS),dtype=np.float32)
        for (i, each) in enumerate(y):
            each[self.y_train[i]] = 1.0
        self.y_train = y
        
        y = np.zeros(shape=(len(self.y_test), CLASS),dtype=np.float32)
        for (i, each) in enumerate(y):
            each[self.y_test[i]] = 1.0
        self.y_test = y
        
        self.x_train /= 255.0
        self.x_test /= 255.0
        
        self.is_train = is_train
        self.current_x = self.x_train if self.is_train else self.x_test
        self.current_y = self.y_train if self.is_train else self.y_test
        
    def size(self):
        return len(self.current_x)
    def get_data(self):
        number = len(self.current_x)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            yield self.current_x[id], self.current_y[id]
    
class Cifar100Dataset(tensorpack.dataflow.RNGDataFlow):
    def __init__(self, root_dir=os.path.join(getHomePath(), 'code/'), is_train=True):
        self.root_dir = root_dir
        self.cifar100 = cPickle.load(open(os.path.join(root_dir, 'cifar-100-python/train'), 'rb'))
        self.x_train = self.cifar100['data']
        self.x_train.resize((self.x_train.shape[0], 32, 32, 3))
        self.y_train = self.cifar100['fine_labels']
        
        self.cifar100_test = cPickle.load(open(os.path.join(root_dir, 'cifar-100-python/test'), 'rb'))
        self.x_test = self.cifar100_test['data']
        self.x_test.resize((self.x_test.shape[0], 32, 32, 3))
        self.y_test = self.cifar100_test['fine_labels']
        
        CLASS = 100
        y = np.zeros(shape=(len(self.y_train), CLASS),dtype=np.float32)
        for (i, each) in enumerate(y):
            each[self.y_train[i]] = 1.0
        self.y_train = y
        
        y = np.zeros(shape=(len(self.y_test), CLASS),dtype=np.float32)
        for (i, each) in enumerate(y):
            each[self.y_test[i]] = 1.0
        self.y_test = y
        
        self.x_train = self.x_train.astype(np.float32)
        self.x_test = self.x_test.astype(np.float32)
        self.x_train /= 255.0
        self.x_test /= 255.0
        
        self.is_train = is_train
        self.current_x = self.x_train if self.is_train else self.x_test
        self.current_y = self.y_train if self.is_train else self.y_test
        
    def size(self):
        return len(self.current_x)
    def get_data(self):
        number = len(self.current_x)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            yield self.current_x[id], self.current_y[id]

import pytreebank
class TreeBankDataset(tensorpack.dataflow.RNGDataFlow):
    TRAIN = 1
    TEST = 2
    DEV = 3
    idToName = {TRAIN:'train', TEST:'test', DEV:'dev'}
    def __init__(self, 
                 root_dir=os.path.join(getHomePath(), 'data/trees/'), 
                 max_len = 60,
                 mode=TRAIN):
        name = TreeBankDataset.idToName[mode]
        self.is_train = (mode == TreeBankDataset.TRAIN)
        self.data = pytreebank.import_tree_corpus(os.path.join(root_dir, '%s.txt'%name))
        self.data = [x.to_labeled_lines()[0] for x in self.data]
        self.max_len = max_len
        self.vocab = tl.nlp.Vocabulary(os.path.join(root_dir, '%s.txt'%'vocab'))
        
    def size(self):
        return len(self.data)
    def get_data(self):
        number = len(self.data)
        numbers = list(range(number))
        for _ in range(number):
            id = random.choice(numbers) if self.is_train else _
            label, sentence = self.data[id]
            sentence = tl.nlp.process_sentence(sentence, None, None)
            sentence = [self.vocab.word_to_id(word) for word in sentence]
            if len(sentence) > self.max_len:
                sentence = sentence[:self.max_len]
            else:
                sentence += [self.vocab.pad_id for _ in range(self.max_len - len(sentence))]
                
            weight = np.array([abs(i - label) + 1.0 for i in range(5)], dtype=np.float32)
            label = np.array([int(i == label) for i in range(5)], dtype=np.float32)
            sentence = np.asarray(sentence, dtype=np.int)
            yield sentence, label, weight