"""
提示词构建服务 - 统一管理所有提示词构建逻辑

整合自:
- backend/app/api/characters.py: build_character_prompt, extract_style_from_template
- backend/app/api/scenes.py: build_scene_prompt, extract_style_from_character_template
"""
from typing import Optional
import json


class PromptBuilder:
    """提示词构建服务"""
    
    # 默认风格
    DEFAULT_CHARACTER_STYLE = "anime style, high quality, detailed"
    DEFAULT_SCENE_STYLE = "anime style, high quality, detailed, environment"
    
    @classmethod
    def build_character_prompt(
        cls,
        name: str,
        appearance: str,
        description: str = "",
        template: Optional[str] = None,
        style: Optional[str] = None
    ) -> str:
        """
        构建角色人设图提示词
        
        Args:
            name: 角色名称
            appearance: 外貌描述
            description: 角色描述（已废弃，不再使用）
            template: 提示词模板，包含 {appearance} 和 {description} 占位符
            style: 风格描述（可选，优先级低于模板中的 style）
            
        Returns:
            构建完成的提示词
        """
        if template:
            # 使用模板构建提示词，只使用 appearance，不使用 description
            prompt = template.replace("{appearance}", appearance or "").replace("{description}", "")
            # 替换 style 占位符
            if "##STYLE##" in prompt:
                final_style = style or cls.DEFAULT_CHARACTER_STYLE
                prompt = prompt.replace("##STYLE##", final_style)
            # 清理多余的逗号和空格
            return cls._clean_prompt(prompt)
        
        # 默认提示词
        base_prompt = "character portrait, high quality, detailed, "
        
        if appearance:
            base_prompt += appearance + ", "
        
        if style:
            base_prompt += style + ", "
        
        base_prompt += "single character, centered, clean background, professional artwork"
        
        return base_prompt
    
    @classmethod
    def build_scene_prompt(
        cls,
        name: str,
        setting: str,
        description: str = "",
        template: Optional[str] = None,
        style: Optional[str] = None
    ) -> str:
        """
        构建场景图提示词
        
        Args:
            name: 场景名称
            setting: 环境设置/布景描述（用于生成场景图）
            description: 场景描述（不使用，保留参数兼容性）
            template: 提示词模板
            style: 风格描述
            
        Note:
            场景图生成只使用 setting 字段，不使用 description 字段
            因为分镜生成时会参考角色图+场景图，场景设定应该是纯环境描述
            
        Returns:
            构建完成的提示词
        """
        if template:
            # 使用模板构建提示词，只使用 setting，忽略 description
            prompt = template.replace("{setting}", setting or "").replace("{description}", "").replace("{name}", name or "")
            # 替换 style 占位符
            if "##STYLE##" in prompt:
                final_style = style or cls.DEFAULT_SCENE_STYLE
                prompt = prompt.replace("##STYLE##", final_style)
            return cls._clean_prompt(prompt)

        # 默认提示词 - 只使用 setting 字段
        base_prompt = "environment design, background art, landscape, "

        if name:
            base_prompt += f"{name}, "

        if setting:
            base_prompt += setting + ", "
        
        if style:
            base_prompt += style + ", "

        base_prompt += "high quality, detailed, no characters, professional artwork"

        return base_prompt
    
    @classmethod
    def extract_style_from_template(cls, template: str) -> str:
        """
        从角色提示词模板中提取 style
        
        Args:
            template: 模板字符串
            
        Returns:
            提取的风格字符串
        """
        if not template:
            return cls.DEFAULT_CHARACTER_STYLE

        # 尝试解析 JSON
        try:
            template_data = json.loads(template)
            if isinstance(template_data, dict) and "style" in template_data:
                return template_data["style"]
        except:
            pass

        # 清理占位符
        style = template.replace("{appearance}", "").replace("{description}", "").strip(", ")
        if style:
            return style

        return cls.DEFAULT_CHARACTER_STYLE
    
    @classmethod
    def extract_style_from_character_template(cls, template: str) -> str:
        """
        从角色提示词模板中提取 style（用于场景图）
        
        比 extract_style_from_template 更激进地清理角色相关内容
        
        Args:
            template: 模板字符串
            
        Returns:
            提取的风格字符串
        """
        if not template:
            return cls.DEFAULT_SCENE_STYLE

        # 尝试解析 JSON
        try:
            template_data = json.loads(template)
            if isinstance(template_data, dict) and "style" in template_data:
                return template_data["style"]
        except:
            pass

        # 清理占位符和角色相关内容
        style = (template.replace("{appearance}", "").replace("{description}", "")
                 .replace("character portrait", "")
                 .replace("single character", "")
                 .replace("centered", "")
                 .replace("colorful", "")
                 .replace("clean background", "")
                 .strip(", ").strip(","))
        
        return cls._clean_prompt(style) or cls.DEFAULT_SCENE_STYLE
    
    @staticmethod
    def _clean_prompt(prompt: str) -> str:
        """
        清理提示词中的冗余内容
        
        Args:
            prompt: 原始提示词
            
        Returns:
            清理后的提示词
        """
        # 合并多余空格
        prompt = " ".join(prompt.split())
        # 清理连续逗号
        prompt = prompt.replace(", ,", ",").replace(",,", ",")
        # 清理 " ," 为 ","
        prompt = prompt.replace(" ,", ",")
        # 清理首尾逗号和空格
        prompt = prompt.strip(", ")
        return prompt


# 便捷函数（保持向后兼容）
def build_character_prompt(
    name: str,
    appearance: str,
    description: str = "",
    template: Optional[str] = None
) -> str:
    """构建角色提示词（便捷函数）"""
    return PromptBuilder.build_character_prompt(name, appearance, description, template)


def build_scene_prompt(
    name: str,
    setting: str,
    description: str = "",
    template: Optional[str] = None,
    style: Optional[str] = None
) -> str:
    """构建场景提示词（便捷函数）"""
    return PromptBuilder.build_scene_prompt(name, setting, description, template, style)


def extract_style_from_template(template: str) -> str:
    """从模板提取风格（便捷函数）"""
    return PromptBuilder.extract_style_from_template(template)


def extract_style_from_character_template(template: str) -> str:
    """从角色模板提取风格用于场景（便捷函数）"""
    return PromptBuilder.extract_style_from_character_template(template)
