# Economist Podcast Studio — 静态视频模板 v3 开发交接文档

> **版本**：v3.0 (Editorial Modern)
> **日期**：2026-09-05
> **原型文件**：`template-v3-prototype.html`（项目根目录，浏览器打开可预览全部效果）
> **目标渲染器**：`skills/economist-static-slide-video/scripts/render_static_slide_template.py`

---

## 1. 设计概述

### 1.1 设计理念

**Editorial Modern（编辑级现代感）**——以暖米白纸张质感为底，保留经济学人红与衬线标题的品牌 DNA，引入层次化排版、无背景描边字幕和极简悬浮图片。

### 1.2 与旧版(v2)的核心差异

| 维度 | 旧版 v2 | 新版 v3 |
|---|---|---|
| 背景 | 深灰 `#262626` | 暖米白 `#F4F1EC` |
| 文字 | 纯白 | 深墨 `#161616` + 灰阶层次 |
| 字幕 | 纯黑底栏 / 渐变遮罩 | 无背景 + 文字描边投影 |
| 图片 | 3px 白边 + contain | 无边框 + 两层柔和投影悬浮 |
| 排版 | 松散，内容页重复封面 | 紧凑编辑级，内容页用文章配图 |
| 元数据 | 底部，与字幕重叠 | 副标题下方，上边框线分隔 |

### 1.3 四种模板画面

1. **横版开篇页** (1920×1080)：左文字 + 右期刊封面
2. **横版内容页** (1920×1080)：左引导问题 + 右文章配图轮播
3. **竖版开篇页** (1080×1920)：上封面 + 下文字
4. **竖版内容页** (1080×1920)：上配图 + 下引导问题

---

## 2. 设计系统

### 2.1 色彩系统

| 用途 | 色值 | 说明 |
|---|---|---|
| 帧背景 | `#F4F1EC` | 暖米白，所有视频帧的底色 |
| 主文字 | `#161616` | 深墨，标题、问题、正文 |
| 次要文字 | `#4A4A4A` | 中文标题、英文副标题 |
| 弱化文字 | `#8A8580` | 元数据、图片说明、中文副标题 |
| 分隔线 | `#D9D4CC` | 细分隔线、元数据上边框 |
| 经济学人红 | `#E3120B` | kicker、编号、装饰线、红点 |
| 字幕描边(英) | `rgba(20,20,20,0.85)` | 英文字幕描边色 |
| 字幕描边(中) | `rgba(20,20,20,0.80)` | 中文字幕描边色 |
| 字幕投影 | `rgba(0,0,0,0.55~0.60)` | 字幕文字投影 |

### 2.2 字体系统

| 用途 | 字体 | 回退 |
|---|---|---|
| 英文标题/问题/副标题 | Georgia | `Times New Roman`, serif |
| 英文 UI/kicker/元数据 | Helvetica Neue | Arial, sans-serif |
| 英文字幕 | Helvetica Neue Bold | Arial Bold, sans-serif |
| 中文全部 | Noto Sans SC | PingFang SC, Microsoft YaHei |
| 图片说明 | Georgia Italic | Times New Roman Italic |

> **Python 实现注意**：PIL 的 `ImageFont.truetype()` 需要字体文件路径。系统字体路径：
> - Georgia: `/System/Library/Fonts/Supplemental/Georgia.ttf` (粗体 `Georgia Bold.ttf`, 斜体 `Georgia Italic.ttf`)
> - Helvetica: `/System/Library/Fonts/Helvetica.ttc`
> - Noto Sans SC: `/System/Library/Fonts/Supplemental/NotoSansCJK-Regular.ttc` (粗体 `NotoSansCJK-Bold.ttc`)
> - 渲染器应内置字体路径解析，找不到时降级到 `DejaVuSans` 等通用字体。

---

## 3. 横版开篇页 (1920×1080)

### 3.1 布局结构

```
┌──────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────┐  ┌──────────────────┐  │
│  │  ── (红装饰线)               │  │                  │  │
│  │  FINANCE · SPECIAL REPORT    │  │    期刊封面       │  │
│  │                               │  │   (contain)      │  │
│  │  The rise of the             │  │                  │  │
│  │  deserving rich               │  │  无边框+两层投影  │  │
│  │  应得富人的崛起               │  │                  │  │
│  │  ───────── (分隔线)           │  │                  │  │
│  │  Today's fortunes are...      │  │                  │  │
│  │  如今的财富更多是...           │  │                  │  │
│  │  ───────── (元数据上边框)      │  │                  │  │
│  │  THE ECONOMIST · 日期 · 时长  │  │                  │  │
│  └─────────────────────────────┘  └──────────────────┘  │
│                                                              │
│              英文字幕（描边+投影）                            │
│              中文字幕（描边+投影）                            │
└──────────────────────────────────────────────────────────┘
```

### 3.2 精确参数

| 元素 | 参数 | 值 |
|---|---|---|
| 文字区 | flex 比例 | 1.15 (约 56.5% 宽度) |
| 文字区 | padding | `44px 36px 100px 48px`（底部 100px 为字幕安全区） |
| 图片区 | flex 比例 | 0.85 (约 43.5% 宽度) |
| 图片区 | padding | `32px 36px 32px 12px` |
| 红色装饰线 | 尺寸 | `36px × 3px`，`#E3120B`，margin-bottom 14px |
| Kicker | 字号/字重 | 11px，Bold，大写，字间距 2.5px，`#E3120B`，margin-bottom 18px |
| 英文标题 | 字号/行高 | 40px Georgia，行高 1.12，`#161616`，margin-bottom 10px |
| 中文标题 | 字号/字重 | 20px Noto Sans SC，600，行高 1.4，`#4A4A4A`，margin-bottom 22px |
| 分隔线 | 尺寸 | 1px 高，`#D9D4CC`，margin-bottom 18px |
| 英文副标题 | 字号/样式 | 17px Georgia Italic，行高 1.5，`#4A4A4A`，margin-bottom 6px |
| 中文副标题 | 字号 | 14px Noto Sans SC，行高 1.5，`#8A8580` |
| 元数据行 | 字号/样式 | 10px Helvetica，大写，字间距 1.5px，`#8A8580`，Bold |
| 元数据行 | 间距 | margin-top 24px，padding-top 16px，border-top 1px `#D9D4CC` |
| 元数据红点 | 尺寸 | 3px 直径圆，`#E3120B`，元素间距 14px |
| 封面图 | 放置 | contain，居中，border-radius 1px |
| 封面图 | 阴影 | `0 4px 10px rgba(0,0,0,0.10), 0 18px 40px rgba(0,0,0,0.22)` |

---

## 4. 横版内容页 (1920×1080)

### 4.1 布局结构

```
┌──────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────┐  ┌──────────────────┐  │
│  │  GUIDE QUESTIONS ────────   │  │                  │  │
│  │                               │  │   文章配图        │  │
│  │  01  Why are the new rich    │  │   (contain)      │  │
│  │      different from the old?  │  │                  │  │
│  │      为什么新富阶层与旧富不同？ │  │  无边框+两层投影  │  │
│  │  ───────── (分隔线)           │  │                  │  │
│  │  02  Does meritocracy justify │  │                  │  │
│  │      inequality?               │  │                  │  │
│  │      精英制度能为不平等辩护吗？  │  │                  │  │
│  │                               │  │  Illustration: ...│  │
│  └─────────────────────────────┘  └──────────────────┘  │
│                                                              │
│              英文字幕（描边+投影）                            │
│              中文字幕（描边+投影）                            │
└──────────────────────────────────────────────────────────┘
```

### 4.2 精确参数

| 元素 | 参数 | 值 |
|---|---|---|
| 文字区 | flex 比例 | 1.1 (约 55% 宽度) |
| 文字区 | padding | `40px 32px 36px 48px` |
| 图片区 | flex 比例 | 0.9 (约 45% 宽度) |
| 图片区 | padding | `36px 36px 28px 16px`，纵向排列 |
| Section Label | 字号/样式 | 10px Helvetica，Bold，大写，字间距 2.5px，`#E3120B`，margin-bottom 28px |
| Section Label | 右侧线 | label 后延伸 1px `#D9D4CC` 横线至文字区右边界 |
| 问题块 | 布局 | flex 横向，gap 18px，margin-bottom 24px |
| 问题编号 | 字号 | 30px Georgia Bold，`#E3120B`，行高 1，padding-top 4px，宽度 32px |
| 英文问题 | 字号/行高 | 22px Georgia，行高 1.3，`#161616`，margin-bottom 6px |
| 中文问题 | 字号 | 14px Noto Sans SC，500，行高 1.5，`#8A8580` |
| 问题分隔线 | 尺寸 | 1px `#D9D4CC`，margin `4px 0 22px` |
| 文章图 | 放置 | contain，居中，max-height 80%，border-radius 1px |
| 文章图 | 阴影 | `0 4px 10px rgba(0,0,0,0.10), 0 16px 36px rgba(0,0,0,0.20)` |
| 图片说明 | 字号/样式 | 11px Georgia Italic，`#8A8580`，margin-top 12px，居中 |

---

## 5. 竖版开篇页 (1080×1920)

### 5.1 布局结构

```
┌──────────────────────────┐
│  ┌──────────────────────┐│
│  │                      ││
│  │     期刊封面          ││
│  │    (contain)          ││
│  │  无边框+两层投影       ││
│  │                      ││
│  └──────────────────────┘│
│  ~~~ 底部渐变到背景色 ~~~ │
│                          │
│  ── (红装饰线)            │
│  FINANCE · SPECIAL REPORT│
│                          │
│  The rise of the         │
│  deserving rich           │
│  应得富人的崛起           │
│  ───────── (分隔线)       │
│  Today's fortunes are... │
│  如今的财富更多是...       │
│  ───────── (元数据上边框)  │
│  THE ECONOMIST · 日期     │
│                          │
│  英文字幕（描边+投影）      │
│  中文字幕（描边+投影）      │
└──────────────────────────┘
```

### 5.2 精确参数

| 元素 | 参数 | 值 |
|---|---|---|
| 封面区 | 高度 | 46% 帧高 |
| 封面区 | padding | `24px 28px 0` |
| 封面区 | 底部渐变 | 40px 高，`linear-gradient(to bottom, transparent, #F4F1EC)` |
| 文字区 | padding | `18px 32px 110px`（底部 110px 字幕安全区） |
| 红色装饰线 | 尺寸 | `28px × 2.5px`，`#E3120B`，margin-bottom 10px |
| Kicker | 字号 | 9px，Bold，大写，字间距 2px，`#E3120B`，margin-bottom 14px |
| 英文标题 | 字号/行高 | 30px Georgia，行高 1.15，`#161616`，margin-bottom 8px |
| 中文标题 | 字号 | 16px Noto Sans SC，600，`#4A4A4A`，margin-bottom 16px |
| 分隔线 | 尺寸 | 1px `#D9D4CC`，margin-bottom 14px |
| 英文副标题 | 字号 | 13px Georgia Italic，行高 1.5，`#4A4A4A`，margin-bottom 4px |
| 中文副标题 | 字号 | 11px Noto Sans SC，行高 1.5，`#8A8580` |
| 元数据行 | 字号 | 8px Helvetica，大写，字间距 1.2px，`#8A8580`，Bold |
| 元数据行 | 间距 | margin-top 16px，padding-top 12px，border-top 1px `#D9D4CC` |
| 元数据红点 | 尺寸 | 2.5px 直径圆，`#E3120B`，元素间距 10px |
| 封面图 | 阴影 | `0 4px 10px rgba(0,0,0,0.10), 0 16px 36px rgba(0,0,0,0.20)` |

---

## 6. 竖版内容页 (1080×1920)

### 6.1 布局结构

```
┌──────────────────────────┐
│  ┌──────────────────────┐│
│  │                      ││
│  │     文章配图          ││
│  │    (contain)          ││
│  │  无边框+两层投影       ││
│  │                      ││
│  └──────────────────────┘│
│  ~~~ 底部渐变到背景色 ~~~ │
│                          │
│  GUIDE QUESTIONS ────── │
│                          │
│  01  Why are the new     │
│      rich different?     │
│      为什么新富阶层不同？  │
│  ───────── (分隔线)       │
│  02  Does meritocracy    │
│      justify inequality? │
│      精英制度能为不平等... │
│                          │
│  英文字幕（描边+投影）      │
│  中文字幕（描边+投影）      │
└──────────────────────────┘
```

### 6.2 精确参数

| 元素 | 参数 | 值 |
|---|---|---|
| 图片区 | 高度 | 42% 帧高 |
| 图片区 | padding | `24px 28px 0` |
| 图片区 | 底部渐变 | 32px 高，`linear-gradient(to bottom, transparent, #F4F1EC)` |
| 文字区 | padding | `18px 28px 24px` |
| Section Label | 字号 | 9px，Bold，大写，字间距 2px，`#E3120B`，margin-bottom 18px |
| 问题块 | gap | 12px，margin-bottom 16px |
| 问题编号 | 字号 | 22px Georgia Bold，`#E3120B`，宽度 24px，padding-top 3px |
| 英文问题 | 字号/行高 | 17px Georgia，行高 1.35，`#161616`，margin-bottom 4px |
| 中文问题 | 字号 | 12px Noto Sans SC，行高 1.5，`#8A8580` |
| 问题分隔线 | margin | `2px 0 16px` |
| 文章图 | 阴影 | `0 3px 8px rgba(0,0,0,0.10), 0 14px 32px rgba(0,0,0,0.18)` |

---

## 7. 字幕渲染规范

### 7.1 设计原则

- **无背景**：不使用任何底栏、渐变遮罩或半透明色块
- **文字描边**：通过文字描边保证在任何背景上的可读性
- **柔和投影**：额外增加一层投影增强立体感和可读性
- **双语垂直排列**：英文在上，中文在下，居中对齐

### 7.2 横版字幕参数

| 元素 | 参数 | 值 |
|---|---|---|
| 字幕区 | padding | `20px 56px 36px`（底部 36px 平台安全区） |
| 字幕区 | 背景 | 透明（无背景） |
| 英文字幕 | 字号/字重 | 18px Helvetica Bold，行高 1.35，字间距 0.1px |
| 英文字幕 | 颜色 | `#FFFFFF` |
| 英文字幕 | 描边 | 1.2px `rgba(20,20,20,0.85)` |
| 英文字幕 | 投影 | `0 2px 10px rgba(0,0,0,0.60)` |
| 英文字幕 | 下边距 | margin-bottom 6px |
| 中文字幕 | 字号/字重 | 14px Noto Sans SC，600，行高 1.4 |
| 中文字幕 | 颜色 | `#FFFFFF` |
| 中文字幕 | 描边 | 0.8px `rgba(20,20,20,0.80)` |
| 中文字幕 | 投影 | `0 2px 8px rgba(0,0,0,0.55)` |

### 7.3 竖版字幕参数

| 元素 | 参数 | 值 |
|---|---|---|
| 字幕区 | padding | `16px 28px 32px` |
| 英文字幕 | 字号 | 15px，描边 0.9px，投影 `0 2px 8px rgba(0,0,0,0.55)` |
| 中文字幕 | 字号 | 12px，描边 0.6px，投影 `0 1px 6px rgba(0,0,0,0.50)` |

### 7.4 字幕换行规则

- 英文：按单词换行，最长两行，超出则自适应缩字号
- 中文：按字符换行，避头尾（标点不在行首），最长两行
- 两种语言独立换行，各自最多两行
- 最小可读字号：英文横版 14px / 竖版 12px；中文横版 11px / 竖版 10px

---

## 8. 图片处理规范

### 8.1 放置方式

- 所有图片使用 **contain** 策略：保持原始宽高比，完整显示，居中放置
- 不裁剪、不拉伸、不变形
- 多余区域露出帧背景色 `#F4F1EC`

### 8.2 视觉处理

- **无边框**：不添加任何白色或彩色边框
- **两层柔和投影**：近景细微阴影 + 远景扩散阴影，模拟悬浮感
- **border-radius**：1px 微圆角（几乎不可见，避免锯齿）

### 8.3 阴影参数表

| 模板 | 阴影 |
|---|---|
| 横版封面 | `0 4px 10px rgba(0,0,0,0.10), 0 18px 40px rgba(0,0,0,0.22)` |
| 横版文章图 | `0 4px 10px rgba(0,0,0,0.10), 0 16px 36px rgba(0,0,0,0.20)` |
| 竖版封面 | `0 4px 10px rgba(0,0,0,0.10), 0 16px 36px rgba(0,0,0,0.20)` |
| 竖版文章图 | `0 3px 8px rgba(0,0,0,0.10), 0 14px 32px rgba(0,0,0,0.18)` |

### 8.4 底部渐变（仅竖版）

竖版开篇页和内容页的图片区域底部有渐变过渡到背景色：
- 开篇页：渐变高度 40px
- 内容页：渐变高度 32px
- 渐变方向：`linear-gradient(to bottom, transparent, #F4F1EC)`

### 8.5 图片轮播（内容页）

- 内容页图片按文章素材顺序（source order）轮播
- 目标停留时间 20 秒（正常范围 18-22 秒）
- 无动画、无过渡、无裁剪，严格顺序切换
- 无文章配图时 fallback 到期刊封面

---

## 9. 自适应机制

### 9.1 长标题自适应（三级兜底）

```
输入标题
  → 测量渲染宽度（PIL font.getbbox / textlength）
  → 超出容器宽度？
    → 是：按单词(英文)/字符(中文)换行
      → 换行后超出最大行数？
        → 是：按比例缩小字号，重新测量
          → 缩小到最小可读字号仍超出？
            → 是：截断，末尾加省略号 "…"
```

**参数：**
- 横版英文标题最大行数：3 行
- 竖版英文标题最大行数：4 行
- 中文标题最大行数：2 行（横版和竖版）
- 最小可读字号：英文横版 24px / 竖版 18px；中文横版 14px / 竖版 12px
- 英文换行：在空格处断开，不拆分单词
- 中文换行：按字符断开，避头尾（`，。、；：！？》」』）`不在行首）

### 9.2 不同比例图片兼容

- contain 策略天然兼容任何比例（1:1, 3:2, 16:9, 21:9, 9:16 等）
- 阴影基于图片实际显示矩形绘制，不是容器矩形
- 实现：先计算 contain 缩放后的实际矩形 `(x, y, w, h)`，再在该矩形位置绘制阴影和图片

### 9.3 异常情况兜底

| 异常 | 处理 |
|---|---|
| 图片加载失败 | fallback 到期刊封面；封面也失败则显示空白区域 |
| 标题为空 | 跳过标题区，副标题上移；全空则显示文章文件名 |
| 字体缺失 | 降级到系统通用字体（DejaVuSans / 文泉驿微米黑） |
| 无文章配图 | 内容页使用期刊封面作为配图 |
| 字幕文本为空 | 不渲染字幕区 |

---

## 10. Python PIL 代码参考

> 以下代码片段展示核心实现逻辑，基于 Pillow (PIL)。渲染器应整合到 `render_static_slide_template.py` 中。

### 10.1 基础工具：颜色与字体加载

```python
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# === 色彩系统 ===
COLORS = {
    "bg":          (244, 241, 236),   # #F4F1EC
    "ink":         (22, 22, 22),      # #161616
    "ink_soft":    (74, 74, 74),      # #4A4A4A
    "muted":       (138, 133, 128),   # #8A8580
    "line":        (217, 212, 204),   # #D9D4CC
    "econ_red":    (227, 18, 11),     # #E3120B
    "white":       (255, 255, 255),
    "stroke_en":   (20, 20, 20, 217), # rgba(20,20,20,0.85)
    "stroke_zh":   (20, 20, 20, 204), # rgba(20,20,20,0.80)
}

# === 字体路径解析 ===
def load_font(name, size, bold=False, italic=False):
    """加载字体，找不到时降级。"""
    paths = {
        "georgia": {
            False: "/System/Library/Fonts/Supplemental/Georgia.ttf",
            True:  "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        },
        "georgia_italic": {
            False: "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
        },
        "helvetica": {
            False: "/System/Library/Fonts/Helvetica.ttc",
            True:  "/System/Library/Fonts/Helvetica.ttc",  # ttc 内含粗体
        },
        "noto_sc": {
            False: "/System/Library/Fonts/Supplemental/NotoSansCJK-Regular.ttc",
            True:  "/System/Library/Fonts/Supplemental/NotoSansCJK-Bold.ttc",
        },
    }
    key = "georgia_italic" if italic and name == "georgia" else name
    font_path = paths.get(key, {}).get(bold, paths.get(key, {}).get(False))
    try:
        return ImageFont.truetype(font_path, size)
    except (IOError, OSError):
        # 降级到默认字体
        return ImageFont.load_default()
```

### 10.2 文本测量与自适应换行

```python
def measure_text(draw, text, font):
    """测量文本渲染尺寸。"""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def wrap_text_en(text, font, max_width, draw, max_lines=3):
    """英文按单词换行，最多 max_lines 行。"""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        w, _ = measure_text(draw, test, font)
        if w <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                # 最后一行，剩余文字全部放入，超出则后续缩字号处理
                remaining = " ".join(words[words.index(word):])
                lines.append(remaining)
                return lines, True  # True = 可能需要缩字号
    if current:
        lines.append(current)
    return lines, False

def fit_text_with_shrink(draw, text, font_name, initial_size, max_width,
                          max_lines, min_size, bold=False, italic=False, lang="en"):
    """
    三级兜底：换行 → 缩字号 → 截断加省略号。
    返回 (lines, final_font, was_truncated)。
    """
    size = initial_size
    while size >= min_size:
        font = load_font(font_name, size, bold=bold, italic=italic)
        if lang == "en":
            lines, need_shrink = wrap_text_en(text, font, max_width, draw, max_lines)
        else:
            lines, need_shrink = wrap_text_zh(text, font, max_width, draw, max_lines)
        if not need_shrink:
            # 检查最后一行是否超出
            last_w, _ = measure_text(draw, lines[-1], font)
            if last_w <= max_width:
                return lines, font, False
        size -= 1
    # 最小字号仍超出，截断
    font = load_font(font_name, min_size, bold=bold, italic=italic)
    lines, _ = wrap_text_en(text, font, max_width, draw, max_lines) if lang == "en" \
                else wrap_text_zh(text, font, max_width, draw, max_lines)
    # 截断最后一行加省略号
    last_line = lines[-1]
    while last_line and measure_text(draw, last_line + "…", font)[0] > max_width:
        last_line = last_line[:-1]
    lines[-1] = last_line + "…"
    return lines, font, True
```

### 10.3 图片 contain 计算与阴影绘制

```python
def calc_contain_rect(img_w, img_h, container_w, container_h, offset_x=0, offset_y=0):
    """计算 contain 策略下图片的实际显示矩形。"""
    scale = min(container_w / img_w, container_h / img_h)
    actual_w = int(img_w * scale)
    actual_h = int(img_h * scale)
    actual_x = offset_x + (container_w - actual_w) // 2
    actual_y = offset_y + (container_h - actual_h) // 2
    return actual_x, actual_y, actual_w, actual_h

def draw_image_with_shadow(canvas, img, rect, shadows, radius=1):
    """
    在指定位置绘制带两层阴影的图片。
    shadows: [(offset_y, offset_x, blur, color_alpha), ...]
    """
    x, y, w, h = rect
    # 逐层绘制阴影（从最底层到最上层）
    for off_y, off_x, blur, color in shadows:
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        sd.rectangle([x + off_x, y + off_y, x + w + off_x, y + h + off_y], fill=color)
        if blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
        canvas = Image.alpha_composite(canvas, shadow_layer)
    # 绘制图片本身（微圆角）
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
        canvas.paste(img.convert("RGBA"), (x, y), mask)
    else:
        canvas.paste(img.convert("RGBA"), (x, y))
    return canvas

# 使用示例（横版封面阴影）：
# shadows = [
#     (4, 0, 5, (0, 0, 0, 26)),    # 近景: 0 4px 10px rgba(0,0,0,0.10)
#     (18, 0, 20, (0, 0, 0, 56)),   # 远景: 0 18px 40px rgba(0,0,0,0.22)
# ]
```

### 10.4 字幕描边渲染（核心）

```python
def draw_stroked_text(canvas, position, text, font, fill_color,
                       stroke_color, stroke_width, shadow_color=(0,0,0,150),
                       shadow_offset=(0, 2), shadow_blur=4):
    """
    绘制带描边和投影的文字（模拟 CSS -webkit-text-stroke + text-shadow）。
    实现方式：8 方向偏移绘制描边层 → 投影层 → 中心文字层。
    """
    x, y = position
    sw = stroke_width

    # === 1. 绘制投影层 ===
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.text((x + shadow_offset[0], y + shadow_offset[1]), text,
            font=font, fill=shadow_color)
    if shadow_blur > 0:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas = Image.alpha_composite(canvas, shadow_layer)

    # === 2. 绘制描边层（8 方向偏移） ===
    stroke_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    st = ImageDraw.Draw(stroke_layer)
    directions = [
        (-sw, -sw), (0, -sw), (sw, -sw),
        (-sw, 0),           (sw, 0),
        (-sw, sw),  (0, sw), (sw, sw),
    ]
    for dx, dy in directions:
        st.text((x + dx, y + dy), text, font=font, fill=stroke_color)
    # 轻微模糊让描边边缘更自然
    stroke_layer = stroke_layer.filter(ImageFilter.GaussianBlur(0.5))
    canvas = Image.alpha_composite(canvas, stroke_layer)

    # === 3. 绘制中心文字层 ===
    cd = ImageDraw.Draw(canvas)
    cd.text((x, y), text, font=font, fill=fill_color)

    return canvas

# 使用示例（横版英文字幕）：
# canvas = draw_stroked_text(
#     canvas, (text_x, text_y), en_text, en_font,
#     fill_color=(255,255,255,255),
#     stroke_color=(20,20,20,217),   # rgba(20,20,20,0.85)
#     stroke_width=2,                  # 1.2px 描边，PIL 中用整数偏移，2px 偏移约等于视觉 1.2px
#     shadow_color=(0,0,0,153),       # rgba(0,0,0,0.6)
#     shadow_offset=(0, 2),
#     shadow_blur=5,
# )
```

### 10.5 底部渐变遮罩（竖版图片区）

```python
def draw_bottom_gradient(canvas, region, gradient_height, bg_color):
    """在指定区域底部绘制渐变到背景色的遮罩。"""
    x, y, w, h = region
    grad = Image.new("RGBA", (1, gradient_height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(gradient_height):
        alpha = int(255 * (i / gradient_height))
        gd.point((0, i), fill=(*bg_color, alpha))
    grad = grad.resize((w, gradient_height))
    canvas.paste(grad, (x, y + h - gradient_height), grad)
    return canvas
```

### 10.6 横版开篇页完整渲染流程（伪代码）

```python
def render_opening_16x9(article, cover_img, caption_en, caption_zh):
    W, H = 1920, 1080
    canvas = Image.new("RGBA", (W, H), (*COLORS["bg"], 255))
    draw = ImageDraw.Draw(canvas)

    # === 文字区 ===
    text_pad = (44, 36, 100, 48)  # top, right, bottom, left
    text_w = int(W * 1.15 / 2.0)   # flex 1.15 / (1.15+0.85)
    text_x = text_pad[3]
    content_w = text_w - text_pad[3] - text_pad[1]
    cur_y = text_pad[0]

    # 红色装饰线
    draw.rectangle([text_x, cur_y, text_x + 36, cur_y + 3], fill=COLORS["econ_red"])
    cur_y += 3 + 14

    # Kicker
    kicker_font = load_font("helvetica", 11, bold=True)
    draw.text((text_x, cur_y), article["kicker"].upper(), font=kicker_font, fill=COLORS["econ_red"])
    cur_y += 11 + 18

    # 英文标题（自适应）
    title_lines, title_font, _ = fit_text_with_shrink(
        draw, article["title_en"], "georgia", 40, content_w,
        max_lines=3, min_size=24, bold=False, lang="en")
    for line in title_lines:
        draw.text((text_x, cur_y), line, font=title_font, fill=COLORS["ink"])
        cur_y += int(40 * 1.12)
    cur_y += 10

    # 中文标题
    zh_title_font = load_font("noto_sc", 20, bold=True)
    draw.text((text_x, cur_y), article["title_zh"], font=zh_title_font, fill=COLORS["ink_soft"])
    cur_y += int(20 * 1.4) + 22

    # 分隔线
    draw.rectangle([text_x, cur_y, text_x + content_w, cur_y + 1], fill=COLORS["line"])
    cur_y += 1 + 18

    # 英文副标题
    sub_en_font = load_font("georgia", 17, italic=True)
    draw.text((text_x, cur_y), article["subtitle_en"], font=sub_en_font, fill=COLORS["ink_soft"])
    cur_y += int(17 * 1.5) + 6

    # 中文副标题
    sub_zh_font = load_font("noto_sc", 14)
    draw.text((text_x, cur_y), article["subtitle_zh"], font=sub_zh_font, fill=COLORS["muted"])
    cur_y += int(14 * 1.5)

    # 元数据行（上边框线）
    cur_y += 24
    draw.rectangle([text_x, cur_y, text_x + content_w, cur_y + 1], fill=COLORS["line"])
    cur_y += 1 + 16
    meta_font = load_font("helvetica", 10, bold=True)
    meta_parts = [article["publication"], article["date"], article["read_time"]]
    mx = text_x
    for i, part in enumerate(meta_parts):
        draw.text((mx, cur_y), part.upper(), font=meta_font, fill=COLORS["muted"])
        w, _ = measure_text(draw, part.upper(), meta_font)
        mx += w + 14
        if i < len(meta_parts) - 1:
            # 红点
            draw.ellipse([mx, cur_y + 4, mx + 3, cur_y + 7], fill=COLORS["econ_red"])
            mx += 3 + 14

    # === 封面图 ===
    img_pad = (32, 36, 32, 12)
    img_x = text_w + img_pad[3]
    img_w = W - img_x - img_pad[1]
    img_h = H - img_pad[0] - img_pad[2]
    rect = calc_contain_rect(cover_img.width, cover_img.height, img_w, img_h, img_x, img_pad[0])
    shadows = [(4, 0, 5, (0,0,0,26)), (18, 0, 20, (0,0,0,56))]
    canvas = draw_image_with_shadow(canvas, cover_img, rect, shadows, radius=1)

    # === 字幕 ===
    cap_pad_bottom = 36
    cap_pad_x = 56
    # 英文字幕（居中，描边）
    en_cap_font = load_font("helvetica", 18, bold=True)
    en_w, en_h = measure_text(draw, caption_en, en_cap_font)
    en_x = (W - en_w) // 2
    en_y = H - cap_pad_bottom - en_h - 6 - 14  # 14 为中文字幕预留
    canvas = draw_stroked_text(canvas, (en_x, en_y), caption_en, en_cap_font,
                                (255,255,255), (20,20,20,217), 2,
                                (0,0,0,153), (0, 2), 5)
    # 中文字幕
    zh_cap_font = load_font("noto_sc", 14, bold=True)
    zh_w, zh_h = measure_text(draw, caption_zh, zh_cap_font)
    zh_x = (W - zh_w) // 2
    zh_y = en_y + en_h + 6
    canvas = draw_stroked_text(canvas, (zh_x, zh_y), caption_zh, zh_cap_font,
                                (255,255,255), (20,20,20,204), 1,
                                (0,0,0,140), (0, 2), 4)

    return canvas.convert("RGB")
```

---

## 11. 文件结构与集成方式

### 11.1 目标文件

```
skills/economist-static-slide-video/
├── scripts/
│   ├── render_static_slide_template.py   # 主渲染器（需重写为 v3）
│   ├── static_slide_storyboard.py         # storyboard 生成（保持不变）
│   └── preview_visual_system.py            # 预览工具（同步更新）
├── templates/
│   ├── podcast-video-visual-system.v3.json # v3 模板配置（新建）
│   └── PODCAST_VIDEO_VISUAL_SYSTEM_V3.md   # v3 模板文档（新建）
└── DESIGN.md                                # 更新为 v3 设计说明
```

### 11.2 模板配置 JSON 结构

```json
{
  "version": "3.0",
  "name": "editorial-modern",
  "colors": {
    "bg": "#F4F1EC",
    "ink": "#161616",
    "ink_soft": "#4A4A4A",
    "muted": "#8A8580",
    "line": "#D9D4CC",
    "econ_red": "#E3120B"
  },
  "fonts": {
    "serif": "Georgia",
    "sans": "Helvetica Neue",
    "cjk": "Noto Sans SC"
  },
  "layouts": {
    "opening_16x9": { "...": "..." },
    "content_16x9": { "...": "..." },
    "opening_9x16": { "...": "..." },
    "content_9x16": { "...": "..." }
  },
  "caption": {
    "background": "none",
    "stroke_en": { "width": 1.2, "color": "rgba(20,20,20,0.85)" },
    "stroke_zh": { "width": 0.8, "color": "rgba(20,20,20,0.80)" },
    "shadow": { "offset": [0, 2], "blur": 5, "color": "rgba(0,0,0,0.6)" }
  },
  "image": {
    "fit": "contain",
    "border": "none",
    "border_radius": 1,
    "shadows": {
      "opening_16x9": [[4, 0, 5, 0.10], [18, 0, 20, 0.22]],
      "content_16x9": [[4, 0, 5, 0.10], [16, 0, 18, 0.20]]
    }
  }
}
```

---

## 12. 验收标准

### 12.1 视觉一致性验收

用与 HTML 原型**完全相同的输入内容**（同一篇文章、同一张封面、同一张配图、同一句字幕）渲染 1920×1080 和 1080×1920 帧，与 HTML 截图并排对比：

- [ ] 背景色一致（`#F4F1EC`）
- [ ] 标题字号、行高、颜色一致
- [ ] 红色装饰线尺寸和位置一致
- [ ] kicker 字号、字间距、颜色一致
- [ ] 分隔线位置和颜色一致
- [ ] 元数据行位置、上边框线、红点一致
- [ ] 图片 contain 放置和阴影效果一致
- [ ] 字幕描边连贯性和投影效果一致
- [ ] 整体布局比例一致（文字区/图片区比例）

### 12.2 兼容性验收

用 5 篇不同特征的文章测试：

- [ ] 超长英文标题（12+ 词）：自适应换行 + 缩字号正常，不溢出
- [ ] 超短标题（2-3 词）：留白合理，不显得空
- [ ] 无文章配图：内容页 fallback 到封面正常
- [ ] 多图文章（5+ 张，含竖图/横图/图表）：轮播正常，不同比例 contain 正常
- [ ] 中文标题超长：按字符换行 + 避头尾正常

### 12.3 异常兜底验收

- [ ] 图片加载失败：不崩溃，显示 fallback
- [ ] 字体缺失：降级到通用字体，不崩溃
- [ ] 字幕为空：不渲染字幕区
- [ ] 标题为空：跳过标题区，布局不崩

### 12.4 性能验收

- [ ] 单帧渲染时间 < 200ms（1920×1080）
- [ ] 单帧渲染时间 < 150ms（1080×1920）
- [ ] 字幕描边 8 方向绘制不产生明显性能问题

---

## 13. 参考资源

- **HTML 原型**：`template-v3-prototype.html`（项目根目录，浏览器打开可交互预览）
- **图片效果对比**：`image-treatment-lab.html`（10 种图片处理方案对比）
- **旧版渲染器**：`skills/economist-static-slide-video/scripts/render_static_slide_template.py`
- **旧版设计文档**：`skills/economist-static-slide-video/DESIGN.md`
- **Storyboard schema**：`skills/economist-static-slide-video/templates/STORYBOARD_SCHEMA.md`

---

> **交接说明**：本文档 + HTML 原型 + 代码参考片段构成完整交接包。开发者应先在浏览器中打开 HTML 原型理解视觉效果，再对照本文档的精确规格清单实现，最后用第 12 节的验收标准逐项验证。代码参考片段中的 `draw_stroked_text` 和 `fit_text_with_shrink` 是核心难点，建议优先实现并单独测试。
