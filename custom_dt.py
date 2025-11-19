import numpy as np
import pandas as pd
import math
from collections import Counter

class Node:

    # Basically after '*' the values has to be passed as Keywords
    def __init__(self, feature = None, threshold = None, left = None, right = None, *, value = None):
        self.feature = feature
        self.threshold = threshold
        self.left = left
        self.right = right
        self.value = value

    def is_leaf_node(self):
        return self.value is not None
        # will return true if value is anything but None

class DecisionTree:

    def __init__(self, max_depth = 20, min_sample_split = 2, n_features = None):
        self.max_depth = max_depth
        self.min_sample_split = min_sample_split
        self.n_features = n_features
        self.root = None

    # X, y are X_train and y_train
    def fit(self, X, y):
        self.n_features = X.shape[1] if not self.n_features else min(X.shape[1], self.n_features)
        self.root = self._grow_tree(X, y, 0)

    def _grow_tree(self, X, y, depth):
        
        # n_samples represents the rows, n_feat are the cols and is feature, n_labels represent unique classes in target col
        n_samples, n_feat = X.shape
        n_labels = len(np.unique(y))

        # if depth goes greater than max_depth or label has a single unique value or sample is less than the min_sample_split we stop
        # Stopping Condition
        if (depth >= self.max_depth or n_labels == 1 or n_samples < self.min_sample_split):
            leaf_values = self._most_common_label(y)
            return Node(value=leaf_values)

        # get the best split

        # get random feature + unique once
        feat_idx = np.random.choice(n_feat, self.n_features, replace = False)

        # we get the best_feature and best_split
        best_feature, best_thres = self._best_split(X, y, feat_idx)

        left_idx, right_idx  =self._split(X[:, best_feature], best_thres)

        left = self._grow_tree(X[left_idx, :], y[left_idx], depth + 1)
        right = self._grow_tree(X[right_idx, :], y[right_idx], depth + 1)

        return Node(feature=best_feature, threshold=best_thres, left=left, right=right)
        
    def _most_common_label(self, y):

        counter = Counter(y)
        value = counter.most_common(1)[0][0]

        # Here in value we get the class with most count with (1) then [0] gives list and another [0] the value
        # so if we have {'yes': 3, 'no': 2}
        # we get [('yes', 3)] then [0] -> ('yes', 3) and [0] -> 'yes'
        # so counter.most_common(1)[0][0] -> 'yes'

        return value

    def _best_split(self, X, y, feat_idx):
        best_gain = -1
        split_idx, split_threshold = None, None

        for idx in feat_idx:
            X_col = X[:, idx]               # take feature col
            threshold = np.unique(X_col)    # gets possible thres from uniq val

            for thr in threshold:
                gain = self._information_gain(X_col, y, thr)

                if gain > best_gain:
                    best_gain = gain
                    split_idx = idx
                    split_threshold = thr

        return split_idx, split_threshold

    def _information_gain(self, X_col, y, thr):
        # parent entropy
        parent_entropy = self._entropy(y)

        # create children
        left_idx, right_idx = self._split(X_col, thr)

        # subclass entropy aka child or weight avg. entropy
        n = len(y)
        n_l, n_r = len(left_idx), len(right_idx)
        e_l, e_r = self._entropy(y[left_idx]), self._entropy(y[right_idx])

        child_entropy = (n_l/n) * e_l + (n_r/n) * e_r

        # parent entropy - child entropy
        information_gain = parent_entropy - child_entropy
        return information_gain
    
    def _entropy(self, y):
        hist = np.bincount(y)
        ps = hist / len(y)

        return -np.sum([p * np.log(p) for p in ps if p > 0])

    def _split(self, X_col, _best_split):
        left_idx = np.argwhere(X_col <= _best_split).flatten()
        right_idx = np.argwhere(X_col > _best_split).flatten()

        return left_idx, right_idx

    def predict(self, X):
        return np.array([self._traverse_tree(i, self.root) for i in X])

    def _traverse_tree(self, i, node):
        if node.is_leaf_node():
            return node.value
        
        if i[node.feature] <= node.threshold:
            return self._traverse_tree(i, node.left)
        
        return self._traverse_tree(i, node.right)