import os
from typing import Union
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from qfluentwidgets import SplashScreen, TitleLabel, FluentIconBase

class CustomSplashScreen(SplashScreen):
    def __init__(self, icon: Union[str, QIcon, FluentIconBase], title: str, parent=None, enableShadow=True):
        super().__init__(icon, parent, enableShadow)
        
        self.titleLabel_custom = TitleLabel(title, self)
        self.titleLabel_custom.setAlignment(Qt.AlignCenter)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        
        iw, ih = self.iconSize().width(), self.iconSize().height()
        icon_y = self.height() // 2 - ih // 2
        
        self.titleLabel_custom.resize(self.width(), 50)
        self.titleLabel_custom.move(0, icon_y + ih + 20)
