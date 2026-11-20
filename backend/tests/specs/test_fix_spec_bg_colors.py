from scripts.fix_spec_bg_colors import convert_bg_colors


def test_convert_bg_colors_matches_catalog():
    colors = [
        " White ",
        "BLUE",
        "red",
        "dark_blue",
        "grey",
        "tint",
        "gradient",
        "sky_blue",
        "gray",
        "dark_red",
    ]
    assert convert_bg_colors(colors) == [
        "#FFFFFF",
        "#438EDB",
        "#FF0000",
        "#1A3B8C",
        "#BFBFBF",
        "#EAF1FB",
        "#438EDB",
        "#87CEEB",
        "#BFBFBF",
        "#8B0000",
    ]


def test_convert_bg_colors_preserves_other_values():
    colors = ["#abcdef", "unknown", "blue"]
    converted = convert_bg_colors(colors)
    assert converted == ["#abcdef", "unknown", "#438EDB"]
    assert colors == ["#abcdef", "unknown", "blue"]
    assert convert_bg_colors(converted) == converted
    assert convert_bg_colors([]) == []
