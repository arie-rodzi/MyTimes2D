# ============================================================
# MyTimes 6-File System — Config + Interface Styles
# ============================================================

SEMESTER_WEEKS = 14
DEFAULT_MIN = 15
DEFAULT_MAX = 17
TARGET_KS = 16
LATE_ENTRY_CUTOFF_WEEK = 10

MAX_SUBJECTS = 2
MAX_CLASSES_SAME_SUBJECT = 3

SCORE_PREF = {1: 100, 2: 80, 3: 60, 4: 40, 5: 20}
SCORE_NOT_PREF = 0

# Fairness dominates preference
W_FAIRNESS = 100000
W_PREF = 10

# Preference compensation for next semester priority
COMPENSATION_POINTS = {
    "Choice 1": 0,
    "Choice 2": 5,
    "Choice 3": 10,
    "Choice 4": 15,
    "Choice 5": 20,
    "Not Preferred": 25,
    "Unassigned": 30,
}


PREMIUM_CSS = """
<style>
:root{
  --navy:#061A40;
  --navy2:#0B3678;
  --gold:#D6B35A;
  --gold2:#F5D27A;
  --ink:#0F172A;
  --muted:#64748B;
  --line:rgba(148,163,184,.22);
  --glass:rgba(255,255,255,.78);
}

.stApp {
  background:
    radial-gradient(circle at top left, rgba(214,179,90,.22), transparent 32%),
    radial-gradient(circle at top right, rgba(11,54,120,.28), transparent 34%),
    linear-gradient(180deg, #F8FAFC 0%, #EEF3F8 45%, #F8FAFC 100%);
}

.block-container {padding-top: 1.2rem; padding-left: 2rem; padding-right: 2rem; max-width: 1500px;}
[data-testid="stSidebar"] {background: linear-gradient(180deg,#061A40 0%,#0B3678 100%);}
[data-testid="stSidebar"] * {color: white !important;}

.mytimes-hero{
  position:relative; overflow:hidden; color:white; padding:42px 44px; border-radius:32px;
  background:
    linear-gradient(135deg, rgba(6,26,64,.98) 0%, rgba(11,54,120,.96) 55%, rgba(6,26,64,.98) 100%);
  box-shadow: 0 28px 70px rgba(6,26,64,.28); margin-bottom:28px; border:1px solid rgba(245,210,122,.28);
}
.mytimes-hero:before{
  content:""; position:absolute; inset:-80px -120px auto auto; width:380px; height:380px;
  background:radial-gradient(circle, rgba(245,210,122,.34), transparent 58%); filter:blur(2px);
}
.mytimes-kicker{letter-spacing:.18em; text-transform:uppercase; color:#F5D27A; font-weight:900; font-size:13px;}
.mytimes-title{font-size:56px; line-height:1; font-weight:1000; margin-top:8px;}
.mytimes-subtitle{font-size:19px; color:#E8EEF9; margin-top:12px; max-width:820px;}
.mytimes-tag-row{display:flex; gap:10px; flex-wrap:wrap; margin-top:22px;}
.mytimes-tag{background:rgba(245,210,122,.13); border:1px solid rgba(245,210,122,.48); color:#FFE8A6; padding:10px 16px; border-radius:999px; font-weight:850; font-size:13px;}

.section-title{font-size:28px; font-weight:1000; color:#061A40; margin:30px 0 6px 0; letter-spacing:-.02em;}
.section-note{font-size:15px; color:#64748B; margin-bottom:16px;}
.soft-card{background:var(--glass); backdrop-filter: blur(16px); border:1px solid rgba(255,255,255,.68); border-radius:28px; padding:24px; box-shadow:0 22px 50px rgba(15,23,42,.08);}
.lux-card{background:linear-gradient(180deg,rgba(255,255,255,.92),rgba(248,250,252,.82)); border:1px solid rgba(214,179,90,.28); border-radius:28px; padding:24px; box-shadow:0 22px 50px rgba(6,26,64,.10);}

.metric-card{position:relative; overflow:hidden; background:linear-gradient(180deg,#FFFFFF 0%,#F8FAFC 100%); border:1px solid rgba(214,179,90,.34); border-radius:26px; padding:22px 23px; box-shadow:0 22px 50px rgba(2,6,23,.10); min-height:132px;}
.metric-card:before{content:""; position:absolute; top:0; left:0; right:0; height:5px; background:linear-gradient(90deg,#061A40,#D6B35A,#0B3678);}
.metric-label{font-size:12px; color:#64748B; text-transform:uppercase; letter-spacing:.12em; font-weight:900;}
.metric-value{font-size:36px; color:#061A40; font-weight:1000; margin-top:10px; letter-spacing:-.04em;}
.metric-note{font-size:13px; color:#64748B; margin-top:6px;}

.stButton > button, .stDownloadButton > button{border-radius:18px !important; border:1px solid rgba(214,179,90,.55) !important; background:linear-gradient(135deg,#061A40 0%,#0B3678 62%,#D6B35A 160%) !important; color:white !important; font-weight:900 !important; padding:.8rem 1rem !important; box-shadow:0 14px 34px rgba(6,26,64,.22) !important;}
.stButton > button:hover, .stDownloadButton > button:hover{transform:translateY(-1px); box-shadow:0 20px 46px rgba(6,26,64,.28) !important;}

[data-testid="stDataFrame"]{border-radius:22px; overflow:hidden; box-shadow:0 16px 34px rgba(15,23,42,.06);}
.stTabs [data-baseweb="tab-list"]{gap:8px;}
.stTabs [data-baseweb="tab"]{background:rgba(255,255,255,.78); border:1px solid rgba(148,163,184,.22); border-radius:16px 16px 0 0; padding:10px 18px; font-weight:850;}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,#061A40,#0B3678) !important; color:white !important;}
.footer{margin-top:38px; padding:22px; color:#64748B; text-align:center; border-top:1px solid #E5E7EB;}
.badge{display:inline-block; padding:7px 12px; border-radius:999px; background:rgba(214,179,90,.16); color:#795B10; font-weight:900; border:1px solid rgba(214,179,90,.34);}
</style>
"""
