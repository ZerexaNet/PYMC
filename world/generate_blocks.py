import urllib.request
import json
import os

input_path = "blocks.json"
output_path = r"C:\Users\hekuo\Desktop\1\pymc\world\blocks.py"

try:
    print(f"正在从 {input_path} 读取数据...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 按 ID 从小到大排列
    data.sort(key=lambda x: x['id'])

    print(f"正在生成文件: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        # 头部注释
        f.write("# -*- coding: utf-8 -*-\n")
        f.write("# 自动从 PrismarineJS minecraft-data 提取\n")
        f.write("# Minecraft 1.21.1 方块状态 ID 注册表 (全局调色板)\n\n")

        state_to_name_lines = []

        for block in data:
            name = block['name']
            display_name = block.get('displayName', name)
            default_state = block['defaultState']
            
            # 变量命名规则: 方块名大写
            # 处理可能的特殊字符（虽然 Minecraft 命名通常很规范）
            var_name = name.upper().replace(" ", "_").replace("-", "_")
            
            # 写入常量
            f.write(f"{var_name} = {default_state}  # {display_name}\n")
            
            # 准备反向字典条目
            state_to_name_lines.append(f"    {default_state}: \"{name}\",")

        # 写入反向字典
        f.write("\n# 方块状态 ID 到名称的映射 (只包含 defaultState)\n")
        f.write("STATE_TO_NAME = {\n")
        # 由于可能存在多个方块对应同一个 defaultState (虽然在 Minecraft 中不太可能，但为了安全按 ID 排序)
        # 这里的 state_to_name 要求是 0: "air", 1: "stone"
        # 按照 state_id 排序写入
        
        # 重新整理字典以确保唯一性并排序
        state_map = {block['defaultState']: block['name'] for block in data}
        sorted_states = sorted(state_map.keys())
        
        for state_id in sorted_states:
            f.write(f"    {state_id}: \"{state_map[state_id]}\",\n")
            
        f.write("}\n")

    print(f"成功生成 {len(data)} 个方块的常量定义。")

except Exception as e:
    print(f"发生错误: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
