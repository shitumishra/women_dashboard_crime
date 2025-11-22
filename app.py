from flask import Flask, render_template, jsonify, request
import pandas as pd
import plotly.graph_objs as go
import plotly.offline as pyo
import os, re, sys

app = Flask(__name__)
DATA_PATH = os.path.join(os.path.dirname(__file__), "crimes.csv")

# ---------- Load and robustly clean ----------
def load_and_clean():
    if not os.path.exists(DATA_PATH):
        print("ERROR: crimes.csv not found at", DATA_PATH, file=sys.stderr)
        return pd.DataFrame()

    # try a few encodings if default fails
    try:
        df = pd.read_csv(DATA_PATH)
    except Exception:
        df = pd.read_csv(DATA_PATH, encoding="latin-1")

    # strip column names
    df.columns = [str(c).strip() for c in df.columns]

    # Drop fully-empty or unnamed columns
    df = df.loc[:, ~df.columns.str.contains('^Unnamed', na=False)]
    df = df.dropna(axis=1, how='all')

    # If there is a merged State+Year column (like "State2017"), try to detect and split it
    for col in df.columns:
        sample = df[col].astype(str).head(30).tolist()
        if sum(1 for v in sample if re.search(r'\D+\d{4}$', str(v))) >= 3:
            # extract state and year
            extracted = df[col].astype(str).str.extract(r'(.+?)(\d{4})$')
            df['State'] = extracted[0].str.strip()
            df['Year'] = pd.to_numeric(extracted[1], errors='coerce')
            df = df.drop(columns=[col])
            break

    # Ensure Year and State exist if possible
    if 'Year' in df.columns:
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce')
    if 'State' in df.columns:
        df['State'] = df['State'].astype(str).str.strip()

    # Reset index and create ID
    df = df.reset_index(drop=True)
    df.insert(0, 'ID', range(1, len(df) + 1))

    # Identify crime columns: anything not ID/State/Year
    non_crime = {'ID','State','Year'}
    crime_cols = [c for c in df.columns if c not in non_crime]

    # Convert crime columns to numeric (remove commas) and fill NaN with 0
    for c in crime_cols:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').str.strip().replace('', '0'), errors='coerce').fillna(0)

    # Recompute crime_cols after conversion (drop any that are all 0)
    crime_cols = [c for c in crime_cols if df[c].sum() != 0]

    # If no crime columns found, keep original ones but ensure numeric conversion
    if len(crime_cols) == 0:
        crime_cols = [c for c in df.columns if c not in non_crime]
        for c in crime_cols:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').str.strip().replace('', '0'), errors='coerce').fillna(0)

    # Save cleaned crime_cols list in dataframe attributes for later
    df.attrs['crime_cols'] = crime_cols
    print("DEBUG: Found crime columns:", crime_cols)
    return df

df_global = load_and_clean()

# ---------- Helper ----------
def top5_from_df(df):
    """Return top 5 crime sums (Series) with exact 5 labels (pad if necessary)."""
    crime_cols = df.attrs.get('crime_cols', [c for c in df.columns if c not in {'ID','State','Year'}])
    if not crime_cols:
        return pd.Series([0,0,0,0,0], index=["NoData1","NoData2","NoData3","NoData4","NoData5"])

    sums = df[crime_cols].sum().sort_values(ascending=False)
    # drop any zero-sum columns (they don't carry info)
    sums = sums[sums > 0]
    # if fewer than 5 non-zero columns, include next highest (even if 0) from original order
    if len(sums) < 5:
        # get remaining columns in original sums (including zeros)
        all_sums = df[crime_cols].sum().sort_values(ascending=False)
        top5 = all_sums.head(5)
    else:
        top5 = sums.head(5)

    # If still fewer than 5 (rare), pad with placeholders
    if len(top5) < 5:
        missing = 5 - len(top5)
        for i in range(missing):
            top5[f"NoData{i+1}"] = 0
    # ensure exactly 5 and preserve order by value desc
    top5 = top5.sort_values(ascending=False).head(5)
    return top5

def make_bar_div(series, title, color):
    # ensure x labels and y values
    x = list(series.index.astype(str))
    y = list(series.values.astype(float))
    max_y = max(y) if len(y) and max(y) > 0 else 1
    fig = go.Figure(go.Bar(x=x, y=y, marker_color=color, text=y, textposition='auto'))
    fig.update_layout(title=title, xaxis_title="Crime Type", yaxis_title="Count",
                      yaxis=dict(range=[0, max_y * 1.2]))
    return pyo.plot(fig, include_plotlyjs=False, output_type='div')

# ---------- Routes ----------
@app.route("/")
def index():
    years = []
    states = []
    if 'Year' in df_global.columns:
        years = sorted(df_global['Year'].dropna().unique().astype(int).tolist())
    if 'State' in df_global.columns:
        states = sorted(df_global['State'].dropna().unique().tolist())
    return render_template("index.html", years=years, states=states, row_count=len(df_global))

@app.route("/update_year", methods=["POST"])
def update_year():
    year = request.form.get("year")
    print("DEBUG /update_year requested, year=", year)
    df = df_global.copy()
    if year and year != "All":
        try:
            ynum = float(year)
            df = df[df['Year'] == ynum]
        except Exception as e:
            print("DEBUG: Year filter parse error:", e)

    top5 = top5_from_df(df)
    div = make_bar_div(top5, f"Top 5 Crimes in Year {year if year and year!='All' else 'All Years'}", "royalblue")
    return jsonify({"plot_html": div})

@app.route("/update_state", methods=["POST"])
def update_state():
    state = request.form.get("state")
    print("DEBUG /update_state requested, state=", state)
    df = df_global.copy()
    if state and state != "All":
        df = df[df['State'] == state]

    top5 = top5_from_df(df)
    div = make_bar_div(top5, f"Top 5 Crimes in {state if state and state!='All' else 'All States'}", "indianred")
    return jsonify({"plot_html": div})

if __name__ == "__main__":
    app.run(debug=True)
