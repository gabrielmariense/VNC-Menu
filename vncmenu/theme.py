"""Paletas de cores e fontes.

THEME e um dict global mutado in-place por apply_color_theme(); os
widgets copiam a cor na criacao, por isso trocar de tema exige
reconstruir a arvore de widgets.

Depende apenas de config.
"""

import customtkinter as ctk

from .config import COLOR_SCHEME_BLUE, COLOR_SCHEME_OPTIONS, COLOR_SCHEME_PURPLE

ctk.set_appearance_mode("Dark")


ctk.set_default_color_theme("blue")


ctk.set_widget_scaling(1.0)


DARK_PURPLE_THEME = {
    "bg": "#21182d",
    "surface": "#2b2039",
    "surface_2": "#38294a",
    "surface_3": "#553d70",
    "border": "#70568d",
    "accent": "#8b5cf6",
    "accent_hover": "#a78bfa",
    "accent_soft": "#634591",
    "text": "#fff9ff",
    "muted": "#d3c0df",
    "button_text": "#ffffff",
    "secondary_button_text": "#ffffff",
    "danger": "#a83b5b",
    "danger_hover": "#c44d70",
    "warning": "#b7793f",
    "warning_hover": "#d39458",
}


LIGHT_PURPLE_THEME = {
    "bg": "#dcb9c5",
    "surface": "#fff4f6",
    "surface_2": "#f1dce4",
    "surface_3": "#d7a8bc",
    "border": "#c792a9",
    "accent": "#7c4dc4",
    "accent_hover": "#693ba9",
    "accent_soft": "#e3bfd0",
    "text": "#2f1d2e",
    "muted": "#674557",
    "button_text": "#ffffff",
    "secondary_button_text": "#2f1d2e",
    "danger": "#a82f4c",
    "danger_hover": "#c23d5c",
    "warning": "#a96832",
    "warning_hover": "#8c5226",
}


# Original blue palettes from the earlier VNC-Menu interface.
DARK_BLUE_THEME = {
    "bg": "#07111f",
    "surface": "#0b1726",
    "surface_2": "#10243a",
    "surface_3": "#1b3554",
    "border": "#2a4a66",
    "accent": "#2f81f7",
    "accent_hover": "#58a6ff",
    "accent_soft": "#1b4d7a",
    "text": "#f8fbff",
    "muted": "#a9bed5",
    "button_text": "#ffffff",
    "secondary_button_text": "#eaf3ff",
    "danger": "#9b2c2c",
    "danger_hover": "#b83a3a",
    "warning": "#b7791f",
    "warning_hover": "#d69e2e",
}


LIGHT_BLUE_THEME = {
    "bg": "#c9d8e8",
    "surface": "#f4f8fc",
    "surface_2": "#e3eef8",
    "surface_3": "#4e6e8e",
    "border": "#9ab0c7",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_soft": "#b9d4f0",
    "text": "#0f1b2a",
    "muted": "#40546a",
    "button_text": "#ffffff",
    "secondary_button_text": "#ffffff",
    "danger": "#b42318",
    "danger_hover": "#d92d20",
    "warning": "#b7791f",
    "warning_hover": "#945c12",
}


THEME = DARK_BLUE_THEME.copy()


def normalize_color_scheme(value) -> str:
    value = str(value or "").strip().lower()
    if value not in COLOR_SCHEME_OPTIONS:
        return COLOR_SCHEME_BLUE
    return value


def color_scheme_display_name(value) -> str:
    return "Azul" if normalize_color_scheme(value) == COLOR_SCHEME_BLUE else "Roxo"


def apply_color_theme(
    dark_mode: bool,
    color_scheme: str = COLOR_SCHEME_BLUE,
):
    """Apply the selected blue or purple palette in dark or light mode."""
    color_scheme = normalize_color_scheme(color_scheme)

    if color_scheme == COLOR_SCHEME_PURPLE:
        palette = DARK_PURPLE_THEME if dark_mode else LIGHT_PURPLE_THEME
    else:
        palette = DARK_BLUE_THEME if dark_mode else LIGHT_BLUE_THEME

    THEME.clear()
    THEME.update(palette)
    ctk.set_appearance_mode("Dark" if dark_mode else "Light")


FONT_TITLE = ("Segoe UI", 24, "bold")


FONT_SUBTITLE = ("Segoe UI", 15, "bold")


FONT_NORMAL = ("Segoe UI", 13)


FONT_BOLD = ("Segoe UI", 13, "bold")


FONT_SMALL = ("Segoe UI", 11)


FONT_SMALL_BOLD = ("Segoe UI", 11, "bold")
