# ============================================================
# PyMC - 类原版地形生成器
# 使用 5 层 Perlin 噪声叠加生成类似原版的自然地形
# ============================================================

"""
类原版地形生成器。

使用与 Minecraft 相同的 Improved Perlin Noise 算法，
通过 5 层八度噪声叠加 (fBm) 生成自然地形。

噪声层设计 (模仿原版 1.18+ 的密度函数系统):

  1. 大陆性噪声 (Continentalness)
     - 决定陆地 vs 海洋的基础分布
     - 低频大振幅，控制大尺度地形走势
     - 缩放: 1/512

  2. 侵蚀噪声 (Erosion)
     - 模拟地质侵蚀效果，决定地形的平坦或崎岖程度
     - 高侵蚀 -> 平原/河谷，低侵蚀 -> 山地
     - 缩放: 1/256

  3. 山峰山谷噪声 (Peaks & Valleys)
     - 在低侵蚀区域产生山峰，在高侵蚀区域产生山谷
     - 缩放: 1/128

  4. 密度噪声 (Density / 3D)
     - 3D 噪声，决定空气/固体的分界面
     - 用于产生悬崖、洞穴入口等 3D 地形特征
     - 缩放: 1/64

  5. 细节噪声 (Detail)
     - 高频噪声，增加地表的微观起伏
     - 缩放: 1/16

地表规则 (Surface Rules):
  根据高度、坡度和噪声值决定地表方块:
  - 基岩层 (y=-64): 最底层
  - 深板岩层 (y<0): 深层石头
  - 石头层: 地下主体
  - 泥土层 (3-4格): 地表以下
  - 草方块: 地表
  - 沙子/砂岩: 海滩和沙漠
  - 砂砾: 河床
  - 水: 海平面以下空气填水
  - 矿石分布: 根据高度和噪声随机嵌入
"""

import math
import random as _random
from functools import lru_cache
from .noise import OctaveNoise, ImprovedNoise
from .biomes import BiomeSampler
from .blocks import (
    AIR, STONE, GRANITE, DIORITE, ANDESITE,
    GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL,
    COBBLESTONE, BEDROCK,
    WATER, SAND, RED_SAND, GRAVEL, SANDSTONE,
    COAL_ORE, IRON_ORE, GOLD_ORE, DIAMOND_ORE, LAPIS_ORE,
    COPPER_ORE, EMERALD_ORE, REDSTONE_ORE,
    DEEPSLATE_COAL_ORE, DEEPSLATE_IRON_ORE, DEEPSLATE_GOLD_ORE,
    DEEPSLATE_DIAMOND_ORE, DEEPSLATE_LAPIS_ORE, DEEPSLATE_COPPER_ORE,
    DEEPSLATE_EMERALD_ORE, DEEPSLATE_REDSTONE_ORE,
    DEEPSLATE, TUFF, CLAY,
    SNOW_BLOCK, SNOW, ICE, PACKED_ICE,
    GRAVEL as GRAVEL_BLOCK,
    OAK_LOG, OAK_LEAVES, BIRCH_LOG, BIRCH_LEAVES,
    SPRUCE_LOG, SPRUCE_LEAVES, JUNGLE_LOG, JUNGLE_LEAVES,
    ACACIA_LOG, ACACIA_LEAVES, CHERRY_LOG, CHERRY_LEAVES,
    DARK_OAK_LOG, DARK_OAK_LEAVES, MANGROVE_LOG, MANGROVE_LEAVES,
    SHORT_GRASS, DANDELION, POPPY,
    DIRT_PATH,
    MOSS_BLOCK,
    SEAGRASS, TALL_SEAGRASS, KELP, KELP_PLANT,
    TUBE_CORAL_BLOCK, BRAIN_CORAL_BLOCK, BUBBLE_CORAL_BLOCK,
    FIRE_CORAL_BLOCK, HORN_CORAL_BLOCK,
    TUBE_CORAL_FAN, BRAIN_CORAL_FAN, BUBBLE_CORAL_FAN,
    FIRE_CORAL_FAN, HORN_CORAL_FAN,
    BLUE_ORCHID, ALLIUM, AZURE_BLUET, RED_TULIP, ORANGE_TULIP,
    WHITE_TULIP, PINK_TULIP, OXEYE_DAISY, CORNFLOWER, LILY_OF_THE_VALLEY,
)

# --------------------------------------------------
# 常量定义
# --------------------------------------------------

# 世界高度范围 (主世界)
MIN_Y = -64          # 最低 Y 坐标
MAX_Y = 319          # 最高 Y 坐标
WORLD_HEIGHT = 384   # 总高度 (MAX_Y - MIN_Y + 1)
SEA_LEVEL = 63       # 海平面高度

# Section 相关
SECTION_HEIGHT = 16
NUM_SECTIONS = WORLD_HEIGHT // SECTION_HEIGHT  # 24


class TerrainGenerator:
    """
    类原版地形生成器。

    使用 5 层 Perlin 噪声模拟 Minecraft 原版地形:
      - 大陆性、侵蚀、山峰山谷、3D 密度、细节噪声
    """

    def __init__(self, seed: int = 0):
        """
        初始化地形生成器。

        参数:
            seed: 世界种子
        """
        self.seed = seed

        # 噪声生成器 (每层使用不同的种子偏移)
        # 为了性能，减少八度数: 2D 噪声用 3 层，3D 噪声用 2 层
        # 第1层: 大陆性噪声 (低频, 大尺度)
        self.continental_noise = OctaveNoise(
            seed=seed + 1,
            octaves=3,
            persistence=0.5,
            lacunarity=2.0
        )

        # 第2层: 侵蚀噪声
        self.erosion_noise = OctaveNoise(
            seed=seed + 2,
            octaves=3,
            persistence=0.45,
            lacunarity=2.0
        )

        # 第3层: 山峰山谷噪声
        self.peaks_noise = OctaveNoise(
            seed=seed + 3,
            octaves=3,
            persistence=0.5,
            lacunarity=2.0
        )

        # 第4层: 3D 密度噪声 (性能关键，只用 2 层)
        self.density_noise = OctaveNoise(
            seed=seed + 4,
            octaves=2,
            persistence=0.5,
            lacunarity=2.0
        )

        # 第5层: 细节噪声 (高频)
        self.detail_noise = OctaveNoise(
            seed=seed + 5,
            octaves=2,
            persistence=0.6,
            lacunarity=2.0
        )

        # 辅助噪声 (地表材质选择)
        self.surface_noise = OctaveNoise(
            seed=seed + 6, octaves=2, persistence=0.5, lacunarity=2.0
        )

        # 温度噪声 (决定雪线等)
        self.temperature_noise = OctaveNoise(
            seed=seed + 7, octaves=2, persistence=0.5, lacunarity=2.0
        )

        # 矿石噪声
        self._ore_rng = _random.Random(seed + 100)
        self.biome_sampler = BiomeSampler(seed)

    # --------------------------------------------------
    # 高度计算
    # --------------------------------------------------

    @lru_cache(maxsize=65536)
    def get_terrain_height(self, world_x: int, world_z: int) -> int:
        """
        计算指定坐标的地形高度 (带缓存)。

        使用与原版类似的多噪声叠加:
        1. 大陆性噪声确定基础海拔
        2. 侵蚀噪声调整平坦/崎岖程度
        3. 山峰噪声产生山地变化
        4. 细节噪声增加微观起伏

        返回:
            地形表面的 Y 坐标
        """
        # 坐标缩放到噪声空间
        nx = world_x / 512.0
        nz = world_z / 512.0

        # --- 1. 大陆性 ---
        # 范围: [-1, 1], 正值 = 陆地, 负值 = 海洋
        continental = self.continental_noise.sample(nx, nz)

        # --- 2. 侵蚀 ---
        # 范围: [-1, 1], 正值 = 高侵蚀(平坦), 负值 = 低侵蚀(崎岖)
        erosion = self.erosion_noise.sample(
            world_x / 256.0, world_z / 256.0
        )

        # --- 3. 山峰山谷 ---
        peaks = self.peaks_noise.sample(
            world_x / 128.0, world_z / 128.0
        )
        # 将山峰噪声转换为山脊形状 (取绝对值后反转)
        # 这样在侵蚀低的地方形成尖锐山峰
        ridge = 1.0 - abs(peaks)

        # --- 4. 细节噪声 ---
        detail = self.detail_noise.sample(
            world_x / 16.0, world_z / 16.0
        )

        # --- 组合计算最终高度 ---

        # 基础高度由大陆性决定
        # continental > 0: 陆地 (高度 64-100+)
        # continental < 0: 海洋 (高度 30-62)
        if continental > 0:
            # 陆地: 海平面以上
            base_height = SEA_LEVEL + continental * 40.0
        else:
            # 海洋/海岸: 海平面以下
            base_height = SEA_LEVEL + continental * 30.0

        # 侵蚀影响地形变化幅度
        # erosion > 0 -> 平坦, erosion < 0 -> 可以有大起伏
        roughness = max(0.0, 1.0 - (erosion + 1.0) * 0.5)  # [0, 1]

        # 山峰贡献 (只在低侵蚀区域显著)
        peak_contribution = ridge * roughness * 60.0

        # 最终高度
        height = base_height + peak_contribution + detail * 4.0

        # 限制范围
        height = max(MIN_Y + 5, min(MAX_Y - 10, height))

        return int(height)

    def get_density(self, world_x: int, world_y: int, world_z: int,
                    surface_height: int) -> float:
        """
        计算 3D 密度值 (用于判断是固体还是空气)。

        密度 > 0: 固体 (石头)
        密度 <= 0: 空气 (或水)

        原版使用密度函数系统，这里简化为基于高度的梯度 + 3D 噪声。

        参数:
            world_x, world_y, world_z: 世界坐标
            surface_height: 该列的地表高度
        """
        # 基础密度: 高度越高越稀疏
        # 在 surface_height 处密度约为 0 (边界)
        base_density = (surface_height - world_y) / 8.0

        # 3D 噪声扰动 (产生悬崖和凹凸)
        density_3d = self.density_noise.sample_3d(
            world_x / 64.0, world_y / 64.0, world_z / 64.0
        )

        return base_density + density_3d * 2.0

    # --------------------------------------------------
    # 区块生成
    # --------------------------------------------------

    def generate_chunk(self, chunk_x: int, chunk_z: int) -> list[list[list[int]]]:
        """
        生成一个区块列的方块数据。

        优化: 只在地表附近 (surface_h +/- DENSITY_MARGIN) 使用 3D 密度采样，
        远离地表的区域直接根据高度判断固体/空气，大幅减少噪声调用。

        参数:
            chunk_x, chunk_z: 区块坐标

        返回:
            3D 方块数组 [y][z][x]，尺寸 384 x 16 x 16
            y=0 对应 world_y = MIN_Y (-64)
        """
        # 3D 密度采样范围: 只在地表上下各 DENSITY_MARGIN 格内采样
        DENSITY_MARGIN = 8

        # 创建 3D 数组: [y从底到顶][z 0-15][x 0-15]
        blocks = [[[AIR for _ in range(16)] for _ in range(16)]
                  for _ in range(WORLD_HEIGHT)]

        # 世界坐标基准
        base_x = chunk_x * 16
        base_z = chunk_z * 16

        # --- 第一步: 计算每列高度并填充基础地形 ---
        height_map = [[0] * 16 for _ in range(16)]

        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz

                # 计算地表高度
                surface_h = self.get_terrain_height(wx, wz)
                height_map[lz][lx] = surface_h

                # 计算填充范围
                si = surface_h - MIN_Y  # 地表数组索引

                # 底部基岩层 (y = -64 ~ -60)
                blocks[0][lz][lx] = BEDROCK
                for bedrock_yi in range(1, 5):
                    rng_val = self._block_hash(wx, MIN_Y + bedrock_yi, wz)
                    if rng_val < (5 - bedrock_yi) * 0.2:
                        blocks[bedrock_yi][lz][lx] = BEDROCK
                    elif MIN_Y + bedrock_yi < 0:
                        blocks[bedrock_yi][lz][lx] = DEEPSLATE
                    else:
                        blocks[bedrock_yi][lz][lx] = STONE

                # 基岩层以上、密度采样区域以下: 直接填充固体
                density_bottom_yi = max(5, si - DENSITY_MARGIN)
                for yi in range(5, density_bottom_yi):
                    wy = MIN_Y + yi
                    if wy < 0:
                        blocks[yi][lz][lx] = DEEPSLATE
                    else:
                        blocks[yi][lz][lx] = STONE

                # 密度采样区域: 使用 3D 噪声决定固体/空气
                density_top_yi = min(WORLD_HEIGHT, si + DENSITY_MARGIN)
                for yi in range(density_bottom_yi, density_top_yi):
                    wy = MIN_Y + yi
                    density = self.get_density(wx, wy, wz, surface_h)
                    if density > 0:
                        if wy < 0:
                            blocks[yi][lz][lx] = DEEPSLATE
                        else:
                            blocks[yi][lz][lx] = STONE
                    else:
                        # 海平面以下填水
                        if wy <= SEA_LEVEL and surface_h < SEA_LEVEL:
                            blocks[yi][lz][lx] = WATER

                # 密度采样区域以上: 水面区域填水，其余空气
                if surface_h < SEA_LEVEL:
                    sea_yi = SEA_LEVEL - MIN_Y
                    for yi in range(density_top_yi, min(sea_yi + 1, WORLD_HEIGHT)):
                        if blocks[yi][lz][lx] == AIR:
                            blocks[yi][lz][lx] = WATER

        # --- 第二步: 应用地表规则 ---
        self._apply_surface_rules(blocks, height_map, base_x, base_z)

        # --- 第三步: 嵌入矿石 ---
        self._place_ores(blocks, base_x, base_z)

        # --- 第四步: 嵌入石头变种 (花岗岩/闪长岩/安山岩) ---
        self._place_stone_variants(blocks, base_x, base_z)

        # --- 第五步: 地表/水下装饰 ---
        self._place_decorations(blocks, height_map, base_x, base_z)

        return blocks

    def _apply_surface_rules(self, blocks, height_map, base_x, base_z):
        """
        应用类原版地表规则。
        根据生物群系/高度/噪声决定地表方块。
        """
        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h = height_map[lz][lx]

                # 地表噪声 (决定是草地/沙子/砂砾等)
                surf_n = self.surface_noise.sample(
                    wx / 48.0, wz / 48.0
                )

                # 温度噪声 (决定雪线)
                temp = self.temperature_noise.sample(
                    wx / 512.0, wz / 512.0
                )

                # 判断地表类型
                is_beach = (SEA_LEVEL - 2 <= surface_h <= SEA_LEVEL + 2
                            and surf_n > -0.3)
                is_desert = surf_n > 0.6 and surface_h < SEA_LEVEL + 15
                is_cold = temp < -0.5 and surface_h > SEA_LEVEL + 10
                is_gravel_beach = (is_beach and surf_n > 0.4)
                is_underwater = surface_h < SEA_LEVEL

                west_h = height_map[lz][max(0, lx - 1)]
                east_h = height_map[lz][min(15, lx + 1)]
                north_h = height_map[max(0, lz - 1)][lx]
                south_h = height_map[min(15, lz + 1)][lx]
                slope = max(
                    abs(surface_h - west_h),
                    abs(surface_h - east_h),
                    abs(surface_h - north_h),
                    abs(surface_h - south_h),
                )

                # 应用地表方块
                si = surface_h - MIN_Y  # 地表数组索引

                if si < 0 or si >= WORLD_HEIGHT:
                    continue

                # 判断当前位置是否为固体 (可能被 3D 噪声挖空)
                if blocks[si][lz][lx] == AIR or blocks[si][lz][lx] == WATER:
                    # 地表被挖空，寻找实际地表
                    for search_y in range(si, max(0, si - 20), -1):
                        if (blocks[search_y][lz][lx] != AIR and
                                blocks[search_y][lz][lx] != WATER):
                            si = search_y
                            surface_h = si + MIN_Y
                            break
                    else:
                        continue

                # --- 放置地表层 ---
                if is_gravel_beach:
                    # 砂砾海滩
                    blocks[si][lz][lx] = GRAVEL
                    for d in range(1, 4):
                        idx = si - d
                        if idx >= 0 and blocks[idx][lz][lx] == STONE:
                            blocks[idx][lz][lx] = DIRT
                elif is_desert:
                    # 沙漠地表
                    blocks[si][lz][lx] = SAND
                    for d in range(1, 5):
                        idx = si - d
                        if idx >= 0 and blocks[idx][lz][lx] == STONE:
                            if d < 3:
                                blocks[idx][lz][lx] = SAND
                            else:
                                blocks[idx][lz][lx] = SANDSTONE
                elif is_beach and not is_underwater:
                    # 沙滩
                    blocks[si][lz][lx] = SAND
                    for d in range(1, 4):
                        idx = si - d
                        if idx >= 0 and blocks[idx][lz][lx] == STONE:
                            if d < 2:
                                blocks[idx][lz][lx] = SAND
                            else:
                                blocks[idx][lz][lx] = SANDSTONE
                elif is_cold:
                    # 寒冷地区: 雪块
                    blocks[si][lz][lx] = SNOW_BLOCK
                    for d in range(1, 4):
                        idx = si - d
                        if idx >= 0 and blocks[idx][lz][lx] == STONE:
                            blocks[idx][lz][lx] = DIRT
                    # 地表放雪
                    if si + 1 < WORLD_HEIGHT and blocks[si + 1][lz][lx] == AIR:
                        blocks[si + 1][lz][lx] = SNOW

                    # 水面结冰
                    water_yi = SEA_LEVEL - MIN_Y
                    if (0 <= water_yi < WORLD_HEIGHT and
                            blocks[water_yi][lz][lx] == WATER):
                        blocks[water_yi][lz][lx] = ICE

                elif is_underwater:
                    # 水下地表
                    if surf_n > 0.2:
                        blocks[si][lz][lx] = CLAY
                    elif surf_n > -0.2:
                        blocks[si][lz][lx] = SAND
                    else:
                        blocks[si][lz][lx] = GRAVEL
                    for d in range(1, 3):
                        idx = si - d
                        if idx >= 0 and blocks[idx][lz][lx] == STONE:
                            blocks[idx][lz][lx] = DIRT
                else:
                    # 普通陆地: 默认草皮。高坡/高海拔处改为更厚的土层，
                    # 减少大片裸露石头带来的“全石头山”观感。
                    top_block = GRASS_BLOCK
                    filler_block = DIRT
                    dirt_depth = 3 + int(abs(surf_n) * 2)

                    if slope >= 4:
                        dirt_depth += 2
                    if slope >= 6:
                        top_block = COARSE_DIRT
                        filler_block = COARSE_DIRT
                    elif slope >= 4 or surface_h > SEA_LEVEL + 45:
                        top_block = COARSE_DIRT

                    blocks[si][lz][lx] = top_block
                    for d in range(1, dirt_depth + 1):
                        idx = si - d
                        if idx >= 0 and blocks[idx][lz][lx] == STONE:
                            blocks[idx][lz][lx] = filler_block if d <= 2 else DIRT

                # 深层替换: 石头->深板岩过渡 (y=0 附近)
                for wy in range(max(0, MIN_Y + 5), 8):
                    yi = wy - MIN_Y
                    if yi < WORLD_HEIGHT and blocks[yi][lz][lx] == STONE:
                        # 渐变过渡: y=0 以下全深板岩, y=0~8 随机过渡
                        if wy < 0:
                            blocks[yi][lz][lx] = DEEPSLATE
                        elif self._block_hash(wx, wy, wz) < 0.5:
                            blocks[yi][lz][lx] = DEEPSLATE

    def _place_stone_variants(self, blocks, base_x, base_z):
        """嵌入石头变种: 花岗岩/闪长岩/安山岩/凝灰岩团簇。"""
        rng = _random.Random(self.seed ^ (base_x * 341873128712 + base_z * 132897987541))

        variants = [
            (GRANITE, 80),    # 花岗岩, 每区块约 80 个
            (DIORITE, 80),    # 闪长岩
            (ANDESITE, 80),   # 安山岩
            (TUFF, 40),       # 凝灰岩 (深层)
        ]

        for block_id, count in variants:
            for _ in range(count):
                lx = rng.randint(0, 15)
                ly_rel = rng.randint(0, 200)  # 从底部算
                lz = rng.randint(0, 15)

                # 凝灰岩只在深层
                if block_id == TUFF and ly_rel > 64:
                    continue

                wy = MIN_Y + ly_rel
                yi = wy - MIN_Y

                # 只替换石头或深板岩
                if (0 <= yi < WORLD_HEIGHT and
                        blocks[yi][lz][lx] in (STONE, DEEPSLATE)):
                    blocks[yi][lz][lx] = block_id

                    # 在周围扩展小团簇 (3x3x3)
                    for dx in range(-1, 2):
                        for dy in range(-1, 2):
                            for dz in range(-1, 2):
                                if rng.random() < 0.4:
                                    nx, ny, nz = lx + dx, yi + dy, lz + dz
                                    if (0 <= nx < 16 and 0 <= nz < 16 and
                                            0 <= ny < WORLD_HEIGHT):
                                        if blocks[ny][nz][nx] in (STONE, DEEPSLATE):
                                            blocks[ny][nz][nx] = block_id

    def _place_ores(self, blocks, base_x, base_z):
        """
        嵌入矿石。模拟原版矿石分布:
        - 煤矿: y=0~320, 在 y=96 附近最多
        - 铜矿: y=-16~112, 在 y=48 附近最多
        - 铁矿: y=-64~320, 双分布 (y=16 和 y=232)
        - 金矿: y=-64~32
        - 红石矿: y=-64~16
        - 青金石矿: y=-64~64, 在 y=0 附近最多
        - 钻石矿: y=-64~16, 在 y=-60 附近最多
        - 绿宝石矿: y=-16~320, 在山地生物群系
        """
        rng = _random.Random(self.seed ^ (base_x * 6364136223846793005 + base_z * 1442695040888963407))

        ore_configs = [
            # (矿石ID, 深板岩变种, 每区块尝试次数, 矿脉大小, y_min, y_max, 最佳y)
            (COAL_ORE, DEEPSLATE_COAL_ORE, 20, 10, 0, 256, 96),
            (IRON_ORE, DEEPSLATE_IRON_ORE, 20, 8, -64, 256, 16),
            (COPPER_ORE, DEEPSLATE_COPPER_ORE, 16, 9, -16, 112, 48),
            (GOLD_ORE, DEEPSLATE_GOLD_ORE, 4, 7, -64, 32, -16),
            (REDSTONE_ORE, DEEPSLATE_REDSTONE_ORE, 8, 6, -64, 16, -32),
            (LAPIS_ORE, DEEPSLATE_LAPIS_ORE, 2, 5, -64, 64, 0),
            (DIAMOND_ORE, DEEPSLATE_DIAMOND_ORE, 2, 4, -64, 16, -60),
            (EMERALD_ORE, DEEPSLATE_EMERALD_ORE, 1, 2, -16, 256, 100),
        ]

        for ore, deep_ore, attempts, vein_size, y_min, y_max, best_y in ore_configs:
            for _ in range(attempts):
                lx = rng.randint(0, 15)
                lz = rng.randint(0, 15)

                # 三角分布: 在 best_y 附近更密集
                wy = int(rng.triangular(y_min, y_max, best_y))
                yi = wy - MIN_Y

                if yi < 0 or yi >= WORLD_HEIGHT:
                    continue

                target = blocks[yi][lz][lx]
                if target == STONE:
                    ore_block = ore
                elif target == DEEPSLATE:
                    ore_block = deep_ore
                else:
                    continue

                # 放置矿脉 (球形散布)
                blocks[yi][lz][lx] = ore_block
                for _ in range(vein_size - 1):
                    dx = rng.randint(-1, 1)
                    dy = rng.randint(-1, 1)
                    dz = rng.randint(-1, 1)
                    nx, ny, nz = lx + dx, yi + dy, lz + dz
                    if 0 <= nx < 16 and 0 <= nz < 16 and 0 <= ny < WORLD_HEIGHT:
                        if blocks[ny][nz][nx] == STONE:
                            blocks[ny][nz][nx] = ore
                        elif blocks[ny][nz][nx] == DEEPSLATE:
                            blocks[ny][nz][nx] = deep_ore

    def _place_decorations(self, blocks, height_map, base_x, base_z):
        """放置树木、花草、海草、珊瑚等装饰，带基础环境校验。"""
        rng = _random.Random(self.seed ^ (base_x * 42317861 + base_z * 9717613))

        for lx in range(16):
            for lz in range(16):
                wx = base_x + lx
                wz = base_z + lz
                surface_h = height_map[lz][lx]
                yi = surface_h - MIN_Y
                if yi < 0 or yi >= WORLD_HEIGHT:
                    continue

                biome = self.biome_sampler.sample_surface_biome(wx, wz, surface_h)
                top_block = blocks[yi][lz][lx]
                above_yi = yi + 1
                if above_yi >= WORLD_HEIGHT:
                    continue

                if top_block in (GRASS_BLOCK, DIRT, COARSE_DIRT, PODZOL, SNOW_BLOCK):
                    if self._should_place_tree(biome, surface_h, rng) and self._is_clear_for_tree(blocks, lx, lz, yi + 1):
                        self._place_tree(blocks, biome, lx, lz, yi + 1, rng)
                        continue

                    if blocks[above_yi][lz][lx] == AIR:
                        self._place_surface_plant(blocks, biome, lx, lz, yi + 1, rng)

                elif top_block in (SAND, RED_SAND, GRAVEL, CLAY) and surface_h < SEA_LEVEL:
                    self._place_underwater_decor(blocks, biome, lx, lz, yi, rng)

    def _should_place_tree(self, biome: str, surface_h: int, rng: _random.Random) -> bool:
        tree_chance = {
            "minecraft:plains": 0.015,
            "minecraft:forest": 0.08,
            "minecraft:flower_forest": 0.07,
            "minecraft:birch_forest": 0.08,
            "minecraft:dark_forest": 0.09,
            "minecraft:jungle": 0.10,
            "minecraft:bamboo_jungle": 0.08,
            "minecraft:sparse_jungle": 0.05,
            "minecraft:taiga": 0.07,
            "minecraft:old_growth_pine_taiga": 0.08,
            "minecraft:old_growth_spruce_taiga": 0.08,
            "minecraft:cherry_grove": 0.06,
            "minecraft:savanna": 0.035,
            "minecraft:savanna_plateau": 0.03,
            "minecraft:windswept_savanna": 0.025,
            "minecraft:mangrove_swamp": 0.04,
            "minecraft:swamp": 0.03,
        }.get(biome, 0.0)

        if surface_h > 130:
            tree_chance *= 0.3
        return rng.random() < tree_chance

    def _is_clear_for_tree(self, blocks, lx: int, lz: int, trunk_base_y: int,
                           radius: int = 2, height: int = 7) -> bool:
        for y in range(trunk_base_y, min(trunk_base_y + height, WORLD_HEIGHT)):
            for dz in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, nz = lx + dx, lz + dz
                    if not (0 <= nx < 16 and 0 <= nz < 16):
                        return False
                    if blocks[y][nz][nx] not in (AIR, WATER):
                        return False
        return True

    def _place_tree(self, blocks, biome: str, lx: int, lz: int, trunk_base_y: int,
                    rng: _random.Random):
        log_block = OAK_LOG
        leaves_block = OAK_LEAVES
        trunk_height = 4 + rng.randint(0, 2)
        canopy_radius = 2

        if biome in {"minecraft:birch_forest", "minecraft:old_growth_birch_forest"}:
            log_block = BIRCH_LOG
            leaves_block = BIRCH_LEAVES
        elif biome in {"minecraft:taiga", "minecraft:old_growth_pine_taiga", "minecraft:old_growth_spruce_taiga"}:
            log_block = SPRUCE_LOG
            leaves_block = SPRUCE_LEAVES
            trunk_height = 5 + rng.randint(0, 2)
        elif biome in {"minecraft:jungle", "minecraft:bamboo_jungle", "minecraft:sparse_jungle"}:
            log_block = JUNGLE_LOG
            leaves_block = JUNGLE_LEAVES
            trunk_height = 6 + rng.randint(0, 2)
        elif biome in {"minecraft:savanna", "minecraft:savanna_plateau", "minecraft:windswept_savanna"}:
            log_block = ACACIA_LOG
            leaves_block = ACACIA_LEAVES
        elif biome == "minecraft:cherry_grove":
            log_block = CHERRY_LOG
            leaves_block = CHERRY_LEAVES
        elif biome in {"minecraft:dark_forest"}:
            log_block = DARK_OAK_LOG
            leaves_block = DARK_OAK_LEAVES
            trunk_height = 5 + rng.randint(0, 1)
        elif biome in {"minecraft:mangrove_swamp", "minecraft:swamp"}:
            log_block = MANGROVE_LOG if biome == "minecraft:mangrove_swamp" else OAK_LOG
            leaves_block = MANGROVE_LEAVES if biome == "minecraft:mangrove_swamp" else OAK_LEAVES

        top_y = min(WORLD_HEIGHT - 1, trunk_base_y + trunk_height)
        for y in range(trunk_base_y, top_y):
            blocks[y][lz][lx] = log_block

        canopy_base = max(trunk_base_y, top_y - 3)
        for y in range(canopy_base, min(top_y + 2, WORLD_HEIGHT)):
            radius = canopy_radius - (1 if y >= top_y else 0)
            for dz in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if abs(dx) + abs(dz) > radius + 1 and rng.random() < 0.6:
                        continue
                    nx, nz = lx + dx, lz + dz
                    if 0 <= nx < 16 and 0 <= nz < 16 and blocks[y][nz][nx] == AIR:
                        blocks[y][nz][nx] = leaves_block

        if top_y < WORLD_HEIGHT and blocks[top_y][lz][lx] == AIR:
            blocks[top_y][lz][lx] = leaves_block

    def _place_surface_plant(self, blocks, biome: str, lx: int, lz: int, plant_y: int,
                             rng: _random.Random):
        flower_tables = {
            "minecraft:flower_forest": [DANDELION, POPPY, ALLIUM, AZURE_BLUET,
                                        RED_TULIP, ORANGE_TULIP, WHITE_TULIP,
                                        PINK_TULIP, OXEYE_DAISY, CORNFLOWER,
                                        LILY_OF_THE_VALLEY],
            "minecraft:cherry_grove": [PINK_TULIP, WHITE_TULIP, ALLIUM],
            "minecraft:meadow": [ALLIUM, AZURE_BLUET, CORNFLOWER, OXEYE_DAISY],
            "minecraft:swamp": [BLUE_ORCHID],
            "minecraft:mangrove_swamp": [BLUE_ORCHID],
            "minecraft:plains": [DANDELION, POPPY, CORNFLOWER],
            "minecraft:sunflower_plains": [DANDELION, POPPY, CORNFLOWER],
        }

        if biome in flower_tables and rng.random() < 0.18:
            blocks[plant_y][lz][lx] = rng.choice(flower_tables[biome])
        elif biome in {"minecraft:plains", "minecraft:forest", "minecraft:birch_forest",
                       "minecraft:flower_forest", "minecraft:meadow", "minecraft:taiga",
                       "minecraft:old_growth_pine_taiga", "minecraft:old_growth_spruce_taiga"} and rng.random() < 0.35:
            blocks[plant_y][lz][lx] = SHORT_GRASS

    def _place_underwater_decor(self, blocks, biome: str, lx: int, lz: int, floor_y: int,
                                rng: _random.Random):
        water_y = floor_y + 1
        if water_y >= WORLD_HEIGHT or blocks[water_y][lz][lx] != WATER:
            return

        if biome in {"minecraft:warm_ocean", "minecraft:lukewarm_ocean"} and rng.random() < 0.08:
            coral_blocks = [
                TUBE_CORAL_BLOCK, BRAIN_CORAL_BLOCK, BUBBLE_CORAL_BLOCK,
                FIRE_CORAL_BLOCK, HORN_CORAL_BLOCK,
            ]
            coral_fans = [
                TUBE_CORAL_FAN, BRAIN_CORAL_FAN, BUBBLE_CORAL_FAN,
                FIRE_CORAL_FAN, HORN_CORAL_FAN,
            ]
            blocks[floor_y][lz][lx] = rng.choice(coral_blocks)
            if water_y < WORLD_HEIGHT and blocks[water_y][lz][lx] == WATER:
                blocks[water_y][lz][lx] = rng.choice(coral_fans)
            return

        if biome in {"minecraft:ocean", "minecraft:deep_ocean", "minecraft:cold_ocean",
                     "minecraft:deep_cold_ocean", "minecraft:lukewarm_ocean",
                     "minecraft:warm_ocean"}:
            if rng.random() < 0.22:
                height = 1 + rng.randint(0, 4)
                for i in range(height):
                    y = water_y + i
                    if y >= WORLD_HEIGHT or blocks[y][lz][lx] != WATER:
                        break
                    blocks[y][lz][lx] = KELP if i == height - 1 else KELP_PLANT
            elif rng.random() < 0.35:
                blocks[water_y][lz][lx] = SEAGRASS

    def _block_hash(self, x: int, y: int, z: int) -> float:
        """
        简单的坐标哈希函数，返回 [0, 1) 的伪随机值。
        用于基岩层随机和其他确定性随机。
        """
        n = x * 374761393 + y * 668265263 + z * 1274126177 + self.seed
        n = (n ^ (n >> 13)) * 1103515245
        n = n ^ (n >> 16)
        return (n & 0x7FFFFFFF) / 0x7FFFFFFF

    def get_height_map(self, chunk_x: int, chunk_z: int) -> list[list[int]]:
        """
        计算区块高度图 (16x16)。

        返回:
            height_map[z][x] = 地表 Y 坐标
        """
        base_x = chunk_x * 16
        base_z = chunk_z * 16
        height_map = [[0] * 16 for _ in range(16)]

        for lx in range(16):
            for lz in range(16):
                height_map[lz][lx] = self.get_terrain_height(
                    base_x + lx, base_z + lz
                )

        return height_map
