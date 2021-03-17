from abc import ABC, abstractmethod
import numpy as np

from ...exceptions import QiskitMachineLearningError


class Loss(ABC):
    """
    Abstract base class for Loss.
    """

    def __call__(self, predict, target):
        self.evaluate(predict, target)

    @abstractmethod
    def evaluate(self, predict, target):
        raise NotImplementedError

    @abstractmethod
    def gradient(self, predict, target):
        raise NotImplementedError


class L2Loss(Loss):

    def evaluate(self, predict, target):
        predict = np.array(predict)
        target = np.array(target)

        if len(predict.shape) <= 1:
            return np.linalg.norm(predict - target)**2
        elif len(predict.shape) > 1:
            return np.linalg.norm(predict - target, axis=len(predict.shape)-1)**2
        else:
            raise QiskitMachineLearningError(f'Invalid shape {predict.shape}!')

    def gradient(self, predict, target):
        predict = np.array(predict)
        target = np.array(target)
        return 2*(predict - target)


class L1Loss(Loss):

    def evaluate(self, predict, target):
        if len(predict.shape) <= 1:
            return np.linalg.norm(predict - target, ord=1)
        elif len(predict.shape) > 1:
            return np.linalg.norm(predict - target, ord=1, axis=len(predict.shape)-1)
        else:
            raise QiskitMachineLearningError(f'Invalid shape {predict.shape}!')

    def gradient(self, predict, target):
        predict = np.array(predict)
        target = np.array(target)
        if len(predict.shape) <= 1:
            return np.linalg.sign(predict - target)
        elif len(predict.shape) > 1:
            return np.linalg.sign(predict - target, axis=len(predict.shape)-1)
        else:
            raise QiskitMachineLearningError(f'Invalid shape {predict.shape}!')


#################################################
#################################################
# TBD
#################################################
#################################################

class L2Loss_Probability(Loss):

    def __init__(self, predict, target):  # predict and target are both probabilities
        super().__init__(predict, target)
        self.joint_keys = set(predict.keys())
        self.joint_keys.update(target.keys())

    def evaluate(self):
        val = 0.0
        for k in self.joint_keys:
            val += (self.predict.get(k, 0) - self.target.get(k, 0))**2
        return val

    def gradient(self):
        val = {}
        for k in self.joint_keys:
            val[k] = 2*(self.predict.get(k, 0) - self.target.get(k, 0))
        return val


class CrossEntropyLoss(Loss):

    def __init__(self, predict, target):  # predict and target are both probabilities
        super().__init__(predict, target)
        self.predict = np.array(predict)
        self.target = np.array(target)

    def evaluate(self):
        return -sum([predict[i]*np.log2(target[i]) for i in range(len(predict))])

    # gradient depends on how to handling softmax


class KLDivergence(Loss):

    def __init__(self, predict, target):  # predict and target are both probabilities
        super().__init__(predict, target)
        self.predict = np.array(predict)
        self.target = np.array(target)

    def evaluate(self):
        return sum(predict[i] * np.log2(predict[i]/target[i]) for i in range(len(predict)))
