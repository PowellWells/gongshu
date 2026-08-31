"""GR-ConvNet v3 architecture.

Adapted from skumra/robotic-grasping commit
183c6f68c44c1c7ff0f07707e2db6fcfd6840d2d under BSD-3-Clause.
Only the inference architecture is retained; training and robot code are not
vendored. See LICENSE in this directory.
"""

from __future__ import annotations

import torch.nn as nn
import torch.nn.functional as F


class GraspModel(nn.Module):
    def predict(self, inputs):
        position, cosine, sine, width = self(inputs)
        return {"pos": position, "cos": cosine, "sin": sine, "width": width}


class ResidualBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int = 3) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, kernel_size, padding=1)
        self.bn1 = nn.BatchNorm2d(in_channels)
        self.conv2 = nn.Conv2d(in_channels, out_channels, kernel_size, padding=1)
        self.bn2 = nn.BatchNorm2d(in_channels)

    def forward(self, inputs):
        values = F.relu(self.bn1(self.conv1(inputs)))
        values = self.bn2(self.conv2(values))
        return values + inputs


class GenerativeResnet(GraspModel):
    def __init__(
        self,
        input_channels: int = 4,
        output_channels: int = 1,
        channel_size: int = 32,
        dropout: bool = False,
        prob: float = 0.0,
    ) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(input_channels, channel_size, kernel_size=9, stride=1, padding=4)
        self.bn1 = nn.BatchNorm2d(channel_size)
        self.conv2 = nn.Conv2d(channel_size, channel_size * 2, kernel_size=4, stride=2, padding=1)
        self.bn2 = nn.BatchNorm2d(channel_size * 2)
        self.conv3 = nn.Conv2d(channel_size * 2, channel_size * 4, kernel_size=4, stride=2, padding=1)
        self.bn3 = nn.BatchNorm2d(channel_size * 4)
        self.res1 = ResidualBlock(channel_size * 4, channel_size * 4)
        self.res2 = ResidualBlock(channel_size * 4, channel_size * 4)
        self.res3 = ResidualBlock(channel_size * 4, channel_size * 4)
        self.res4 = ResidualBlock(channel_size * 4, channel_size * 4)
        self.res5 = ResidualBlock(channel_size * 4, channel_size * 4)
        self.conv4 = nn.ConvTranspose2d(
            channel_size * 4,
            channel_size * 2,
            kernel_size=4,
            stride=2,
            padding=1,
            output_padding=1,
        )
        self.bn4 = nn.BatchNorm2d(channel_size * 2)
        self.conv5 = nn.ConvTranspose2d(
            channel_size * 2,
            channel_size,
            kernel_size=4,
            stride=2,
            padding=2,
            output_padding=1,
        )
        self.bn5 = nn.BatchNorm2d(channel_size)
        self.conv6 = nn.ConvTranspose2d(channel_size, channel_size, kernel_size=9, stride=1, padding=4)
        self.pos_output = nn.Conv2d(channel_size, output_channels, kernel_size=2)
        self.cos_output = nn.Conv2d(channel_size, output_channels, kernel_size=2)
        self.sin_output = nn.Conv2d(channel_size, output_channels, kernel_size=2)
        self.width_output = nn.Conv2d(channel_size, output_channels, kernel_size=2)
        self.dropout = dropout
        self.dropout_pos = nn.Dropout(p=prob)
        self.dropout_cos = nn.Dropout(p=prob)
        self.dropout_sin = nn.Dropout(p=prob)
        self.dropout_wid = nn.Dropout(p=prob)

        for module in self.modules():
            if isinstance(module, (nn.Conv2d, nn.ConvTranspose2d)):
                nn.init.xavier_uniform_(module.weight, gain=1)

    def forward(self, inputs):
        values = F.relu(self.bn1(self.conv1(inputs)))
        values = F.relu(self.bn2(self.conv2(values)))
        values = F.relu(self.bn3(self.conv3(values)))
        values = self.res1(values)
        values = self.res2(values)
        values = self.res3(values)
        values = self.res4(values)
        values = self.res5(values)
        values = F.relu(self.bn4(self.conv4(values)))
        values = F.relu(self.bn5(self.conv5(values)))
        values = self.conv6(values)
        if self.dropout:
            return (
                self.pos_output(self.dropout_pos(values)),
                self.cos_output(self.dropout_cos(values)),
                self.sin_output(self.dropout_sin(values)),
                self.width_output(self.dropout_wid(values)),
            )
        return (
            self.pos_output(values),
            self.cos_output(values),
            self.sin_output(values),
            self.width_output(values),
        )
