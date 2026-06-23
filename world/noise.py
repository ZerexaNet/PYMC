# ============================================================
# PyMC - Improved Perlin Noise 实现
# 基于 Ken Perlin 2002 年的改进版噪声算法
# 与 Minecraft 原版使用的算法相同
# ============================================================

"""
Improved Perlin Noise 实现。

Minecraft 使用的是 Ken Perlin 在 2002 年发表的改进版 Perlin Noise 算法，
特点是使用固定的排列表和梯度向量，并通过 fade 函数实现平滑插值。

本模块提供:
  - ImprovedNoise: 单层 Perlin 噪声生成器 (可指定随机种子偏移)
  - OctaveNoise: 多层叠加噪声 (fBm / 分形布朗运动)
"""

import math
import random


# Ken Perlin 的标准排列表 (0-255 的随机排列)
_PERLIN_PERMUTATION = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
    140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148,
    247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32,
    57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122,
    60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54,
    65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169,
    200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64,
    52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212,
    207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213,
    119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9,
    129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104,
    218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241,
    81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157,
    184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93,
    222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
]


def _fade(t: float) -> float:
    """
    Perlin 的 fade 函数: 6t^5 - 15t^4 + 10t^3
    提供比线性插值更平滑的过渡。
    """
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp(t: float, a: float, b: float) -> float:
    """线性插值。"""
    return a + t * (b - a)


def _grad(hash_val: int, x: float, y: float, z: float) -> float:
    """
    梯度函数。
    根据哈希值的低 4 位选择 12 个梯度方向之一。
    这是 Ken Perlin 改进版算法的核心优化。
    """
    h = hash_val & 15
    u = x if h < 8 else y
    if h < 4:
        v = y
    elif h == 12 or h == 14:
        v = x
    else:
        v = z
    return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)


class ImprovedNoise:
    """
    Improved Perlin Noise 生成器。

    每个实例有自己的排列表 (通过种子打乱)，
    以及随机的坐标偏移量，确保不同实例生成不同的噪声。
    """

    def __init__(self, rng: random.Random = None):
        """
        初始化噪声生成器。

        参数:
            rng: 随机数生成器 (用于打乱排列表和生成偏移)
        """
        if rng is None:
            rng = random.Random()

        # 生成随机坐标偏移 (与 Minecraft 一致)
        self.x_offset = rng.random() * 256.0
        self.y_offset = rng.random() * 256.0
        self.z_offset = rng.random() * 256.0

        # 创建排列表的副本并打乱
        self.perm = list(_PERLIN_PERMUTATION)
        # 从后向前进行 Fisher-Yates 洗牌 (与 Minecraft 一致)
        for i in range(255, 0, -1):
            j = rng.randint(0, i)
            self.perm[i], self.perm[j] = self.perm[j], self.perm[i]

        # 扩展排列表到 512 (避免取模运算)
        self.perm = self.perm + self.perm

    def noise(self, x: float, y: float, z: float = 0.0) -> float:
        """
        计算 3D Perlin 噪声值。

        参数:
            x, y, z: 采样坐标

        返回:
            噪声值，范围大约在 [-1, 1]
        """
        # 加上偏移
        x = x + self.x_offset
        y = y + self.y_offset
        z = z + self.z_offset

        # 找到所在单元格 (取整)
        xi = int(math.floor(x)) & 255
        yi = int(math.floor(y)) & 255
        zi = int(math.floor(z)) & 255

        # 单元格内的相对位置
        xf = x - math.floor(x)
        yf = y - math.floor(y)
        zf = z - math.floor(z)

        # 计算 fade 曲线
        u = _fade(xf)
        v = _fade(yf)
        w = _fade(zf)

        # 哈希 8 个角点
        p = self.perm
        a = p[xi] + yi
        aa = p[a] + zi
        ab = p[a + 1] + zi
        b = p[xi + 1] + yi
        ba = p[b] + zi
        bb = p[b + 1] + zi

        # 三线性插值
        return _lerp(w,
            _lerp(v,
                _lerp(u, _grad(p[aa], xf, yf, zf),
                         _grad(p[ba], xf - 1, yf, zf)),
                _lerp(u, _grad(p[ab], xf, yf - 1, zf),
                         _grad(p[bb], xf - 1, yf - 1, zf))),
            _lerp(v,
                _lerp(u, _grad(p[aa + 1], xf, yf, zf - 1),
                         _grad(p[ba + 1], xf - 1, yf, zf - 1)),
                _lerp(u, _grad(p[ab + 1], xf, yf - 1, zf - 1),
                         _grad(p[bb + 1], xf - 1, yf - 1, zf - 1))))

    def noise2d(self, x: float, z: float) -> float:
        """2D 噪声 (y=0 的切片)。"""
        return self.noise(x, 0.0, z)


class OctaveNoise:
    """
    多层叠加噪声 (分形布朗运动 / fBm)。

    将多层不同频率和振幅的 Perlin 噪声叠加在一起，
    产生更自然、更细节丰富的地形。

    Minecraft 原版的地形噪声使用类似的叠加方式:
      - 低层 (低频高振幅): 决定大尺度地形形状
      - 高层 (高频低振幅): 添加细节和粗糙度

    参数说明:
      - octaves: 叠加层数 (Minecraft 一般用 4-8 层)
      - persistence: 每层振幅衰减系数 (一般 0.5)
      - lacunarity: 每层频率增长系数 (一般 2.0)
    """

    def __init__(self, seed: int, octaves: int = 5,
                 persistence: float = 0.5, lacunarity: float = 2.0):
        """
        初始化多层噪声。

        参数:
            seed: 随机种子
            octaves: 叠加层数
            persistence: 振幅衰减系数
            lacunarity: 频率增长系数
        """
        self.octaves = octaves
        self.persistence = persistence
        self.lacunarity = lacunarity

        # 为每一层创建独立的噪声生成器 (不同种子)
        self.noise_layers: list[ImprovedNoise] = []
        rng = random.Random(seed)
        for _ in range(octaves):
            self.noise_layers.append(ImprovedNoise(rng))

        # 预计算归一化因子 (使输出范围接近 [-1, 1])
        self._max_value = 0.0
        amplitude = 1.0
        for _ in range(octaves):
            self._max_value += amplitude
            amplitude *= persistence

    def sample(self, x: float, z: float) -> float:
        """
        采样 2D 多层叠加噪声。

        参数:
            x, z: 世界坐标

        返回:
            归一化后的噪声值，范围大约 [-1, 1]
        """
        total = 0.0
        amplitude = 1.0
        frequency = 1.0

        for layer in self.noise_layers:
            total += layer.noise2d(x * frequency, z * frequency) * amplitude
            amplitude *= self.persistence
            frequency *= self.lacunarity

        # 归一化
        return total / self._max_value

    def sample_3d(self, x: float, y: float, z: float) -> float:
        """
        采样 3D 多层叠加噪声 (用于洞穴等 3D 特征)。

        参数:
            x, y, z: 世界坐标

        返回:
            归一化后的噪声值
        """
        total = 0.0
        amplitude = 1.0
        frequency = 1.0

        for layer in self.noise_layers:
            total += layer.noise(x * frequency, y * frequency,
                                z * frequency) * amplitude
            amplitude *= self.persistence
            frequency *= self.lacunarity

        return total / self._max_value
