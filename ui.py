"""Look and feel, matched to the Friends of the Children - Chicago website (colors sampled from the site; fonts are free
Google Fonts that resemble the site's headline and body type). Prototype styling only: confirm brand use with Friends Chicago."""
import streamlit as st

CHARCOAL, BLACK = "#282828", "#000000"
GREY, GREY_LIGHT = "#555555", "#919191"
BLUE, BLUE_INK, BLUE_TINT = "#4CA7E8", "#1A74B8", "#EEF5FB"
ORANGE, ORANGE_BTN, ORANGE_HOVER = "#EC6237", "#C94A20", "#A93C17"
NAVY = "#265A82"
FONT = "Roboto, Arial, sans-serif"
FONT_COND = "'Roboto Condensed', 'Arial Narrow', Arial, sans-serif"
# 1-5 scale: low scores warm, high scores cool
SCALE = {1: "#C94A20", 2: "#F2A488", 3: "#DADADA", 4: "#A6D1F2", 5: BLUE}
BAND = {"High": ORANGE, "Medium": "#F7B89E", "Low": BLUE}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@600;700&family=Roboto:wght@400;500;700&display=swap');
:root {{ --charcoal:{CHARCOAL}; --grey:{GREY}; --blue:{BLUE}; --blue-ink:{BLUE_INK}; --orange:{ORANGE}; --tint:{BLUE_TINT}; }}
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp select, .stApp button,
.stApp [data-baseweb], .stApp [data-testid="stMarkdownContainer"] {{ font-family:{FONT}; }}
.stApp [data-testid="stIconMaterial"], .stApp span[class*="material"] {{ font-family:"Material Symbols Rounded", "Material Icons" !important; }}
.stApp {{ background:#FFFFFF; color:{GREY}; }}
.block-container {{ padding-top:4.5rem; max-width:1180px; }}

/* headlines: condensed, uppercase, with the blue bar */
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ font-family:{FONT_COND} !important; text-transform:uppercase; letter-spacing:.015em; color:{GREY}; font-weight:700; }}
.stApp h1 {{ font-size:2.7rem; line-height:1.05; }}
.stApp h1::after {{ content:""; display:block; width:84px; height:7px; background:{BLUE}; margin-top:12px; }}
.stApp h2 {{ font-size:1.65rem; }}
.stApp h3 {{ font-size:1.3rem; color:{CHARCOAL}; }}
.stApp [data-testid="stCaptionContainer"] {{ color:{GREY}; }}

/* sidebar: charcoal like the site header; brand block first */
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{ display:flex; flex-direction:column; }}
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ order:-1; }}
/* sidebar: charcoal like the site header */
section[data-testid="stSidebar"] {{ background:{CHARCOAL}; }}
section[data-testid="stSidebar"] * {{ color:#FFFFFF; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {{ font-family:{FONT_COND}; text-transform:uppercase; letter-spacing:.04em; font-size:1.05rem; border-radius:0; border-left:5px solid transparent; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{ background:rgba(76,167,232,.22); border-left:5px solid {BLUE}; }}
section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {{ background:rgba(255,255,255,.08); }}
section[data-testid="stSidebar"] button {{ background:transparent; border:1px solid #FFFFFF; border-radius:2px; font-family:{FONT_COND}; text-transform:uppercase; letter-spacing:.04em; }}
section[data-testid="stSidebar"] button:hover {{ background:{ORANGE_BTN}; border-color:{ORANGE_BTN}; }}
section[data-testid="stSidebar"] [data-testid="stAlert"] {{ background:#3A3A3A; border:1px solid {ORANGE}; border-left:6px solid {ORANGE}; }}
.brand {{ font-family:{FONT_COND}; font-weight:700; font-size:1.55rem; line-height:1.05; letter-spacing:.12em; color:#FFFFFF; padding:6px 0 4px 0; }}
.brand b {{ color:{BLUE}; }}
.brand-sub {{ color:{BLUE}; font-weight:700; font-size:.95rem; margin-bottom:6px; }}

/* buttons */
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {{ background:{ORANGE_BTN}; color:#FFFFFF; border:0; border-radius:2px; font-family:{FONT_COND}; text-transform:uppercase; font-weight:700; font-size:1.1rem; letter-spacing:.04em; padding:.45rem 1.4rem; }}
button[data-testid="stBaseButton-primary"]:hover, button[data-testid="stBaseButton-primaryFormSubmit"]:hover {{ background:{ORANGE_HOVER}; color:#FFFFFF; }}
button[data-testid="stBaseButton-secondary"] {{ border:2px solid {CHARCOAL}; border-radius:2px; color:{CHARCOAL}; font-family:{FONT_COND}; text-transform:uppercase; font-weight:700; letter-spacing:.04em; }}
button[data-testid="stBaseButton-secondary"]:hover {{ border-color:{ORANGE_BTN}; color:{ORANGE_BTN}; }}
.stApp a {{ color:{BLUE_INK}; }}

/* form controls: orange accents */
[data-baseweb="radio"] > div:first-child {{ border-color:{ORANGE_BTN} !important; }}
[data-baseweb="radio"] input:checked + div, [data-baseweb="radio"] [aria-checked="true"] > div:first-child {{ background-color:{ORANGE_BTN} !important; border-color:{ORANGE_BTN} !important; }}
[data-baseweb="checkbox"] [aria-checked="true"] > div:first-child {{ background-color:{ORANGE_BTN} !important; border-color:{ORANGE_BTN} !important; }}
[data-testid="stSlider"] [role="slider"] {{ background-color:{ORANGE_BTN} !important; }}
[data-testid="stSlider"] [data-testid="stThumbValue"] {{ color:{ORANGE_BTN} !important; font-weight:700; }}

/* tabs */
button[data-baseweb="tab"] {{ font-family:{FONT_COND}; text-transform:uppercase; letter-spacing:.05em; font-size:1.1rem; font-weight:700; color:{GREY}; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color:{BLUE_INK}; }}
div[data-baseweb="tab-highlight"] {{ background:{ORANGE}; height:4px; }}
div[data-baseweb="tab-border"] {{ background:#D9D9D9; }}

/* metric tiles */
[data-testid="stMetric"] {{ background:{BLUE_TINT}; border-left:7px solid {BLUE}; padding:14px 18px; border-radius:2px; }}
[data-testid="stMetricLabel"] {{ color:{GREY}; font-weight:500; }}
[data-testid="stMetricValue"] {{ font-family:{FONT_COND}; font-weight:700; font-size:2.6rem; color:{CHARCOAL}; line-height:1.1; }}

/* notices */
[data-testid="stAlert"] {{ border-radius:2px; border-left:6px solid {BLUE}; }}
[data-testid="stExpander"] {{ border:1px solid #D9D9D9; border-radius:2px; }}
[data-testid="stExpander"] summary {{ font-family:{FONT_COND}; text-transform:uppercase; letter-spacing:.03em; font-weight:700; }}
[data-testid="stProgress"] div[role="progressbar"] > div {{ background:{BLUE}; }}
blockquote {{ border-left:6px solid {BLUE}; padding:.2rem 1rem; color:{CHARCOAL}; background:{BLUE_TINT}; }}
blockquote p {{ color:{CHARCOAL}; font-size:1.05rem; }}

/* login hero */
.hero {{ position:relative; min-height:430px; background:{BLUE}; clip-path:polygon(14% 0, 100% 0, 100% 100%, 0 100%); display:flex; align-items:flex-end; justify-content:flex-end; padding:0; }}
.hero .stat {{ background:{NAVY}; color:#FFFFFF; padding:22px 30px; margin:0 0 0 0; min-width:62%; }}
.hero .stat .big {{ font-family:{FONT_COND}; font-weight:700; font-size:3.2rem; line-height:1; text-transform:uppercase; color:#FFFFFF; }}
.hero .stat .small {{ font-family:{FONT_COND}; font-weight:700; font-size:1.6rem; text-transform:uppercase; color:#FFFFFF; }}
.kicker {{ font-family:{FONT_COND}; font-weight:700; font-size:1.4rem; text-transform:uppercase; color:{GREY_LIGHT}; margin:0; }}
@media (max-width: 800px) {{ .hero {{ min-height:200px; clip-path:none; }} }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_brand():
    st.markdown("<div class='brand'>MENTOR<br>CHECK-<b>1</b>N</div>", unsafe_allow_html=True)
    st.markdown("<div class='brand-sub'>Friends of the Children · Chicago</div>", unsafe_allow_html=True)


def login_hero():
    st.markdown("<div class='hero'><div class='stat'><div class='big'>12.5 years</div><div class='small'>No matter what</div></div></div>",
                unsafe_allow_html=True)


def style(chart, height=None):
    """Apply the brand look to an Altair chart. Use with st.altair_chart(..., theme=None)."""
    if height:
        chart = chart.properties(height=height)
    return (chart.configure_view(strokeWidth=0)
            .configure_axis(labelFont=FONT, titleFont=FONT, labelColor=GREY, titleColor=GREY, gridColor="#E6E6E6",
                            domainColor="#BDBDBD", tickColor="#BDBDBD", labelLimit=320)
            .configure_legend(labelFont=FONT, titleFont=FONT, labelColor=GREY, orient="bottom", title=None)
            .configure_title(font=FONT_COND, color=GREY, anchor="start", fontSize=16))


def section(title, purpose=None, level=2):
    """A clear heading with one line saying what the chart or table is for and how to use it."""
    if level == 2:
        st.subheader(title)
    else:
        st.markdown(f"#### {title}")
    if purpose:
        st.caption(purpose)
