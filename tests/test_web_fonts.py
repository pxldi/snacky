from importlib.resources import files

FONTS = (
    "bricolage-grotesque-extrabold.woff2",
    "fira-sans-condensed-regular.woff2",
    "fira-sans-condensed-bold.woff2",
    "fira-sans-compressed-heavy.woff2",
)


def test_font_files_ship_and_fonts_css_references_them() -> None:
    static = files("snacky.web") / "static"
    css = (static / "fonts.css").read_text()
    for name in FONTS:
        assert (static / "fonts" / name).is_file()
        assert f"/static/fonts/{name}" in css
    assert (static / "fonts" / "OFL-Fira-Sans.txt").is_file()
    assert (static / "fonts" / "OFL-Bricolage-Grotesque.txt").is_file()
