# import torch
# import torch.nn as nn
# import torch.nn.functional as F

from tinygrad import Tensor, dtypes, nn
import tinygrad
import numpy as np
# @torch.no_grad()
def symlog(x):
    # return torch.sign(x) * torch.log(1 + torch.abs(x))
    return Tensor.sign(x) * Tensor.log(1 + Tensor.abs(x))


# @torch.no_grad()
def symexp(x):
    # return torch.sign(x) * (torch.exp(torch.abs(x)) - 1)
    return Tensor.sign(x) * (Tensor.exp(Tensor.abs(x)) - 1)

def mse_loss(x, y):
    return Tensor.square(x - y).mean()
class SymLogLoss:
    def __init__(self):
        # super().__init__()
        pass

    def forward(self, output, target):
        target = symlog(target)
        # return 0.5*F.mse_loss(output, target)
        return 0.5*mse_loss(output, target)


class SymLogTwoHotLoss:
    def __init__(self, num_classes, lower_bound, upper_bound):
        # super().__init__()
        self.num_classes = num_classes
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.bin_length = (upper_bound - lower_bound) / (num_classes-1)

        # # use register buffer so that bins move with .cuda() automatically
        # self.bins: torch.Tensor
        # self.register_buffer(
        #     'bins', torch.linspace(-20, 20, num_classes), persistent=False)
        
        self.bins = Tensor(np.linspace(-20, 20, num_classes))
        # import sys
        # self.bins.realize()
        # print(self.bins, self.bins.dtype)
        # sys.exit()


    def forward(self, output:Tensor, target):
        target = symlog(target)
        assert target.min() >= self.lower_bound and target.max() <= self.upper_bound

        # index = torch.bucketize(target, self.bins)
        # diff = target - self.bins[index-1]  # -1 to get the lower bound
        # weight = diff / self.bin_length
        # weight = torch.clamp(weight, 0, 1)
        # weight = weight.unsqueeze(-1)
        
        index = np.digitize(target, self.bins)
        diff = target - self.bins[index-1]  # -1 to get the lower bound
        weight = diff / self.bin_length
        weight = weight.clip(0, 1)
        weight = weight.unsqueeze(-1)

        # target_prob = (1-weight)*F.one_hot(index-1, self.num_classes) + weight*F.one_hot(index, self.num_classes)
        target_prob = (1-weight)*(index-1).one_hot(self.num_classes) + weight*index.one_hot(self.num_classes)

        # loss = -target_prob * F.log_softmax(output, dim=-1)
        loss = -target_prob * output.log_softmax(axis=-1)
        loss = loss.sum(dim=-1)
        return loss.mean()

    def decode(self, output:Tensor):
        # return symexp(F.softmax(output, dim=-1) @ self.bins)
        return symexp(output.softmax(axis=-1) @ self.bins)


if __name__ == "__main__":
    loss_func = SymLogTwoHotLoss(255, -20, 20)
    # output = torch.randn(1, 1, 255).requires_grad_()
    output = Tensor.randn(1, 1, 255)
    # target = torch.ones(1).reshape(1, 1).float() * 0.1
    target = Tensor.ones(1).reshape((1, 1)).float() * 0.1
    print(target)
    loss = loss_func(output, target)
    print(loss)

    # prob = torch.ones(1, 1, 255)*0.5/255
    # prob[0, 0, 128] = 0.5
    # logits = torch.log(prob)
    # print(loss_func.decode(logits), loss_func.bins[128])
