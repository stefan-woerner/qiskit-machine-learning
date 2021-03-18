# This code is part of Qiskit.
#
# (C) Copyright IBM 2020, 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""A Sampling Neural Network based on a given quantum circuit."""

from typing import Tuple, Union, List, Callable, Optional, Dict, cast

import numpy as np
from sparse import SparseArray, DOK

from qiskit import QuantumCircuit
from qiskit.circuit import Parameter
from qiskit.opflow import Gradient, CircuitSampler, CircuitStateFn
from qiskit.providers import BaseBackend, Backend
from qiskit.utils import QuantumInstance

from .sampling_neural_network import SamplingNeuralNetwork
from ..exceptions import QiskitMachineLearningError


class CircuitQNN(SamplingNeuralNetwork):
    """A Sampling Neural Network based on a given quantum circuit."""

    def __init__(self, circuit: QuantumCircuit,
                 input_params: Optional[List[Parameter]] = None,
                 weight_params: Optional[List[Parameter]] = None,
                 dense: bool = False,
                 return_samples: bool = False,
                 interpret: Optional[Callable[[int], Union[int, Tuple[int, ...]]]] = None,
                 output_shape: Union[int, Tuple[int, ...]] = None,
                 gradient: Gradient = None,
                 quantum_instance: Optional[Union[QuantumInstance, BaseBackend, Backend]] = None
                 ) -> None:
        """Initializes the Circuit Quantum Neural Network.

        Args:
            circuit: The (parametrized) quantum circuit that generates the samples of this network.
            input_params: The parameters of the circuit corresponding to the input.
            weight_params: The parameters of the circuit corresponding to the trainable weights.
            dense: Returns whether the output is dense or not.
            return_samples: Determines whether the network returns a batch of samples or (possibly
                sparse) array of probabilities in its forward pass. In case of probabilities,
                the backward pass returns the probability gradients, while it returns (None, None)
                in the case of samples. Note that return_samples==True will always result in a
                dense return array independent of the other settings.
            interpret: A callable that maps the measured integer to another unsigned integer or
                tuple of unsigned integers. These are used as new indices for the (potentially
                sparse) output array. If this is used, the output shape of the output needs to be
                given as a separate argument.
            output_shape: The output shape of the custom interpretation.
            gradient: The gradient converter to be used for the probability gradients.
            quantum_instance: The quantum instance to evaluate the circuits.

        Raises:
            QiskitMachineLearningError: if `interpret` is passed without `output_shape`.
        """

        # TODO: currently cannot handle statevector simulator, at least throw exception

        # copy circuit and add measurements in case non are given
        self._circuit = circuit.copy()
        if quantum_instance.is_statevector:
            if len(self._circuit.clbits) > 0:
                self._circuit.remove_final_measurements()
        elif len(self._circuit.clbits) == 0:
            self._circuit.measure_all()

        self._input_params = list(input_params or [])
        self._weight_params = list(weight_params or [])
        self._interpret = interpret
        if return_samples:
            output_shape_ = output_shape if output_shape else (1,)
        else:
            output_shape_ = (2**circuit.num_qubits,)
        if interpret:
            if output_shape is None:
                raise QiskitMachineLearningError(
                    'No output shape given, but required in case of custom interpret!')
            output_shape_ = output_shape

        self._gradient = gradient

        if isinstance(quantum_instance, (BaseBackend, Backend)):
            quantum_instance = QuantumInstance(quantum_instance)
        self._quantum_instance = quantum_instance

        # TODO this should not be necessary... but currently prop grads fail otherwise
        from qiskit import Aer
        self._sampler = CircuitSampler(Aer.get_backend('statevector_simulator'), param_qobj=False)

        # construct probability gradient opflow object
        grad_circuit = circuit.copy()
        grad_circuit.remove_final_measurements()  # TODO: ideally this would not be necessary
        params = list(input_params) + list(weight_params)
        self._grad_circuit = Gradient().convert(CircuitStateFn(grad_circuit), params)

        super().__init__(len(self._input_params), len(self._weight_params), dense, return_samples,
                         output_shape_)

    @ property
    def circuit(self) -> QuantumCircuit:
        """Returns the underlying quantum circuit."""
        return self._circuit

    @ property
    def input_params(self) -> List:
        """Returns the list of input parameters."""
        return self._input_params

    @ property
    def weight_params(self) -> List:
        """Returns the list of trainable weights parameters."""
        return self._weight_params

    @ property
    def quantum_instance(self) -> QuantumInstance:
        """Returns the quantum instance to evaluate the circuits."""
        return self._quantum_instance

    def _sample(self, input_data: np.ndarray, weights: np.ndarray) -> np.ndarray:
        if self._quantum_instance.is_statevector:
            raise QiskitMachineLearningError('Sampling does not work with statevector simulator!')

        # combine parameter dictionary
        param_values = {p: input_data[i] for i, p in enumerate(self.input_params)}
        param_values.update({p: weights[i] for i, p in enumerate(self.weight_params)})

        # evaluate operator
        orig_memory = self.quantum_instance.backend_options.get('memory')
        self.quantum_instance.backend_options['memory'] = True
        result = self.quantum_instance.execute(self.circuit.bind_parameters(param_values))
        self.quantum_instance.backend_options['memory'] = orig_memory

        # return samples
        memory = result.get_memory()
        samples = np.zeros((1, len(memory), *self.output_shape))
        for i, b in enumerate(memory):
            sample = int(b, 2)
            if self._interpret:
                sample = cast(int, self._interpret(sample))
            samples[0, i, :] = sample
        return samples

    def _probabilities(self, input_data: np.ndarray, weights: np.ndarray
                       ) -> Union[np.ndarray, SparseArray]:
        # combine parameter dictionary
        param_values = {p: input_data[i] for i, p in enumerate(self.input_params)}
        param_values.update({p: weights[i] for i, p in enumerate(self.weight_params)})

        # evaluate operator
        result = self.quantum_instance.execute(
            self.circuit.bind_parameters(param_values))
        counts = result.get_counts()
        shots = sum(counts.values())

        # initialize probabilities
        prob: Union[np.ndarray, SparseArray] = None
        if self.dense:
            prob = np.zeros((1, *self.output_shape))
        else:
            prob = DOK((1, *self.output_shape))

        # evaluate probabilities
        for b, v in counts.items():
            key = int(b, 2)
            if self._interpret:
                key = cast(int, self._interpret(key))
            prob[0, key] += v / shots

        return prob

    def _probability_gradients(self, input_data: np.ndarray, weights: np.ndarray
                               ) -> Tuple[Union[np.ndarray, SparseArray],
                                          Union[np.ndarray, SparseArray]]:
        # combine parameter dictionary
        param_values = {p: input_data[i] for i, p in enumerate(self.input_params)}
        param_values.update({p: weights[i] for i, p in enumerate(self.weight_params)})

        # TODO: additional "bind_parameters" should not be necessary, seems like a bug to be fixed
        grad = self._sampler.convert(self._grad_circuit, param_values
                                     ).bind_parameters(param_values).eval()

        # TODO: map to dictionary to pretend sparse logic --> needs to be fixed in opflow!
        input_grad_dicts: List[Dict] = []
        if self.num_inputs > 0:
            input_grad_dicts = [{} for _ in range(self.num_inputs)]
            for i in range(self.num_inputs):
                for k in range(2 ** self.circuit.num_qubits):
                    key = k
                    if self._interpret:
                        key = cast(int, self._interpret(key))
                    input_grad_dicts[i][key] = (input_grad_dicts[i].get(key, 0.0) +
                                                np.real(grad[i][k]))

        weights_grad_dicts: List[Dict] = []
        if self.num_weights > 0:
            weights_grad_dicts = [{} for _ in range(self.num_weights)]
            for i in range(self.num_weights):
                for k in range(2 ** self.circuit.num_qubits):
                    key = k
                    if self._interpret:
                        key = cast(int, self._interpret(key))
                    weights_grad_dicts[i][key] = (weights_grad_dicts[i].get(key, 0.0) +
                                                  np.real(grad[i + self.num_inputs][k]))

        input_grad: Union[np.ndarray, SparseArray] = None
        weights_grad: Union[np.ndarray, SparseArray] = None
        if self._dense:
            input_grad = np.zeros((1, self.num_inputs, *self.output_shape))
            weights_grad = np.zeros((1, self.num_weights, *self.output_shape))
        else:
            if self.num_inputs > 0:
                input_grad = DOK((1, self.num_inputs, *self.output_shape))
            else:
                input_grad = np.zeros((1, self.num_inputs, *self.output_shape))
            if self.num_weights > 0:
                weights_grad = DOK((1, self.num_weights, *self.output_shape))
            else:
                weights_grad = np.zeros((1, self.num_weights, *self.output_shape))

        for i in range(self.num_inputs):
            for k, grad in input_grad_dicts[i].items():
                input_grad[0, i, k] = grad

        for i in range(self.num_weights):
            for k, grad in weights_grad_dicts[i].items():
                weights_grad[0, i, k] = grad

        return input_grad, weights_grad
