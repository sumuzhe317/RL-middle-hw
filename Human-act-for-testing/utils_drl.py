from typing import (
    Optional,
)

import random

import torch
import torch.nn.functional as F
import torch.optim as optim

import numpy as np

from utils_types import (
    TensorStack4,
    TorchDevice,
)

from utils_memory import ReplayMemory
from utils_model import DQN


class Agent(object):

    def __init__(
            self,
            action_dim: int,
            device: TorchDevice,
            gamma: float,
            seed: int,

            eps_start: float,
            eps_final: float,
            eps_decay: float,

            restore: Optional[str] = None,
    ) -> None:
        self.__action_dim = action_dim
        self.__device = device
        self.__gamma = gamma

        self.__eps_start = eps_start
        self.__eps_final = eps_final
        self.__eps_decay = eps_decay

        self.__eps = eps_start
        self.__r = random.Random()
        self.__r.seed(seed)

        self.__policy = DQN(action_dim, device).to(device)
        self.__target = DQN(action_dim, device).to(device)
        if restore is None:
            self.__policy.apply(DQN.init_weights)
        else:
            self.__policy.load_state_dict(torch.load(restore))
        self.__target.load_state_dict(self.__policy.state_dict())
        self.__optimizer = optim.Adam(
            self.__policy.parameters(),
            lr=0.0000625,
            eps=1.5e-4,
        )
        self.__target.eval()
        # act like a human
        self.chose_be: int = int(0)
        self.act_be: int = int(0)
        self.action_cnt = list()
        self.action_cnt.append(0)
        self.action_cnt.append(0)
        self.action_cnt.append(0)
        self.action_reset = 0

    def run(self, state: TensorStack4, training: bool = False, testing: bool = False) -> int:
        """run suggests an action for the given state."""
        if training:
            self.__eps -= \
                (self.__eps_start - self.__eps_final) / self.__eps_decay
            self.__eps = max(self.__eps, self.__eps_final)

        if testing or self.__r.random() > self.__eps:
            with torch.no_grad():
                abs_sub = 0.95
                tmp = self.__policy(state)
                tmpmax = tmp.max(1)[0]
                tmpmin = tmp.min(1)[0]
                if(tmpmax-tmpmin>=abs_sub):
                    action = tmp.max(1).indices.item()
                    self.chose_be = action
                    if(self.act_be != action):
                        self.action_reset += 1
                    self.act_be = action
                else:
                    chose = tmp.max(1).indices.item()
                    if(chose == self.chose_be):
                        action = chose
                        if(self.act_be != action):
                            self.action_reset += 1
                        self.act_be = action
                    else:
                        action = self.act_be
                        self.chose_be = chose
                self.action_cnt[action] += 1
                return action
        return self.__r.randint(0, self.__action_dim - 1)

    def learn(self, memory: ReplayMemory, batch_size: int) -> float:
        return self.random_learn(memory,batch_size)

    def prior_learn(self, memory: ReplayMemory, batch_size: int) -> float:
        """learn trains the value network via TD-learning."""
        p = 0.00001
        weight = None
        with torch.no_grad():
            state_batch, action_batch, reward_batch, next_batch, done_batch = \
                memory.full_sample()
            values = self.__policy(state_batch.float()).gather(1, action_batch)
            values_next = self.__target(next_batch.float()).max(1).values.detach()
            expected = (self.__gamma * values_next.unsqueeze(1)) * \
                (1. - done_batch) + reward_batch
            weight = torch.abs(expected-values) + p
            weight = weight.reshape(-1)

        weight = weight.cpu().detach().numpy()
        weight = weight/weight.sum()
        indices =  np.random.choice(a=np.arange(weight.size),size=batch_size,replace=False,p=weight)
        indices = torch.tensor(indices).to(self.__device)
        # indices = torch.multinomial(input=weight, num_samples=batch_size,replacement=False)

        # print(indices)

        state_batch, action_batch, reward_batch, next_batch, done_batch = \
            memory.index_sample(indices)

        values = self.__policy(state_batch.float()).gather(1, action_batch)
        values_next = self.__target(next_batch.float()).max(1).values.detach()
        expected = (self.__gamma * values_next.unsqueeze(1)) * \
            (1. - done_batch) + reward_batch
        loss = F.smooth_l1_loss(values, expected)

        self.__optimizer.zero_grad()
        loss.backward()
        for param in self.__policy.parameters():
            param.grad.data.clamp_(-1, 1)
        self.__optimizer.step()

        return loss.item()

    def random_learn(self, memory: ReplayMemory, batch_size: int) -> float:
        """learn trains the value network via TD-learning."""
        state_batch, action_batch, reward_batch, next_batch, done_batch = \
            memory.sample(batch_size)

        values = self.__policy(state_batch.float()).gather(1, action_batch)
        values_next = self.__target(next_batch.float()).max(1).values.detach()
        expected = (self.__gamma * values_next.unsqueeze(1)) * \
            (1. - done_batch) + reward_batch
        loss = F.smooth_l1_loss(values, expected)

        self.__optimizer.zero_grad()
        loss.backward()
        for param in self.__policy.parameters():
            param.grad.data.clamp_(-1, 1)
        self.__optimizer.step()

        return loss.item()

    def sync(self) -> None:
        """sync synchronizes the weights from the policy network to the target
        network."""
        self.__target.load_state_dict(self.__policy.state_dict())

    def save(self, path: str) -> None:
        """save saves the state dict of the policy network."""
        torch.save(self.__policy.state_dict(), path)
