# This code is part of Qiskit.
#
# (C) Copyright IBM 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""A connector to use Qiskit (Quantum) Neural Networks as PyTorch modules."""

import logging
import numpy as np
from qiskit.exceptions import MissingOptionalLibraryError

from ..neural_networks import NeuralNetwork
from ..exceptions import QiskitMachineLearningError

logger = logging.getLogger(__name__)

try:
    from torch import Tensor
    from torch.autograd import Function
    from torch.nn import Module, Parameter as TorchParam
except ImportError:
    if logger.isEnabledFor(logging.INFO):
        EXC = MissingOptionalLibraryError(
            libname='Pytorch',
            name='TorchConnector',
            pip_install="pip install 'qiskit-machine-learning[torch]'")
        logger.info(str(EXC))


class TorchConnector(Module):
    """ Connects Qiskit (Quantum) Neural Network to PyTorch."""

    class _TorchNNFunction(Function):

        @staticmethod
        def forward(ctx, input, weights, qnn):
            """ Forward pass computation.
            Args:
                ctx: context
                input: data input (torch tensor)
                weights: weight input (torch tensor)
                qnn: operator QNN
            """

            # TODO: efficiently handle batches (for input and weights)
            # validate input shape
            if input.shape[-1] != qnn.num_inputs:
                raise QiskitMachineLearningError(
                    f'Invalid input dimension! Received {input.shape} and ' +
                    f'expected input compatible to {qnn.num_inputs}')

            result = qnn.forward(input.numpy(), weights.numpy())
            result = np.array(result)
            if len(result.shape) == 0:
                result = np.array([result])
            result = Tensor(result)
            ctx.qnn = qnn
            ctx.save_for_backward(input, weights)
            return result

        @staticmethod
        def backward(ctx, grad_output):
            """ Backward pass computation.
            Args:
                ctx: context
                grad_output: previous gradient
             """

            # get context data
            input, weights = ctx.saved_tensors
            qnn = ctx.qnn

            # TODO: efficiently handle batches (for input and weights)
            # validate input shape
            if input.shape[-1] != qnn.num_inputs:
                raise QiskitMachineLearningError(
                    f'Invalid input dimension! Received {input.shape} and ' +
                    f' expected input compatible to {qnn.num_inputs}')

            # evaluate QNN gradient
            input_grad, weights_grad = qnn.backward(input.numpy(), weights.numpy())
            if input_grad is not None:
                if np.prod(input_grad.shape) == 0:
                    input_grad = None
                else:
                    if len(input_grad.shape) == 1:
                        input_grad = input_grad.reshape(1, len(input_grad))
                    input_grad = grad_output.float() * Tensor(input_grad)
            if weights_grad is not None:
                if np.prod(weights_grad.shape) == 0:
                    weights_grad = None
                else:
                    if len(weights_grad.shape) == 1:
                        weights_grad = weights_grad.reshape(1, len(weights_grad))
                    weights_grad = grad_output.float() @ Tensor(weights_grad)

            # return gradients for the first two arguments and None for the others
            return input_grad, weights_grad, None

    def __init__(self, nn: NeuralNetwork):
        """Initializes the TorchConnector."""
        super().__init__()
        self._nn = nn
        self._weights = TorchParam(Tensor(nn.num_weights))
        self._weights.data.uniform_(-1, 1)  # TODO: enable more reasonable initialization

    def forward(self, input: Tensor = None) -> Tensor:
        """Forward pass.
        Args:
            input: data to be evaluated.
        Returns:
            Result of forward pass of this model.
        """
        input_ = input if input is not None else Tensor([])
        return TorchConnector._TorchNNFunction.apply(input_, self._weights, self._nn)