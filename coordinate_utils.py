"""
座標轉換工具模組
處理 AI 代理標準化座標（0-1000）與實際螢幕像素座標之間的轉換
"""


def denormalize_x(x: int, screen_width: int) -> int:
    """
    將標準化 X 座標（0-1000）轉換為實際螢幕像素座標
    
    Args:
        x: 標準化座標（0-1000）
        screen_width: 螢幕寬度（像素）
    
    Returns:
        實際像素座標
    
    Example:
        >>> denormalize_x(500, 1440)  # 中間位置
        720
    """
    return int(x / 1000 * screen_width)


def denormalize_y(y: int, screen_height: int) -> int:
    """
    將標準化 Y 座標（0-1000）轉換為實際螢幕像素座標
    
    Args:
        y: 標準化座標（0-1000）
        screen_height: 螢幕高度（像素）
    
    Returns:
        實際像素座標
    
    Example:
        >>> denormalize_y(500, 900)  # 中間位置
        450
    """
    return int(y / 1000 * screen_height)


def normalize_x(x: int, screen_width: int) -> int:
    """
    將實際螢幕像素座標轉換為標準化 X 座標（0-1000）
    （保留作為工具函數）
    
    Args:
        x: 實際像素座標
        screen_width: 螢幕寬度（像素）
    
    Returns:
        標準化座標（0-1000）
    """
    return int(x / screen_width * 1000)


def normalize_y(y: int, screen_height: int) -> int:
    """
    將實際螢幕像素座標轉換為標準化 Y 座標（0-1000）
    （保留作為工具函數）
    
    Args:
        y: 實際像素座標
        screen_height: 螢幕高度（像素）
    
    Returns:
        標準化座標（0-1000）
    """
    return int(y / screen_height * 1000)
