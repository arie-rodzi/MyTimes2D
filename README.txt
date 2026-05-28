MyTimes 6-File System
===================

Run:
    pip install streamlit pandas numpy openpyxl pulp plotly
    streamlit run app.py

Files:
1. app.py               Main Streamlit app and workflow
2. config_styles.py     Constants and interface CSS
3. ui_components.py     Hero, KPI cards and reusable UI components
4. data_utils.py        File reading, cleaning, preparation, export helpers
5. optimizer.py         Fair KS optimizer and output builder
6. emergency_engine.py  Emergency reallocation engine with repeated log support

Workflow:
1. Upload Files
2. Data Validation
3. Class Manager
4. Run Fair KS Allocation
5. Emergency Reallocation
6. Manual Fine Tuning
7. Executive Dashboard and Export

Important logic:
- UI wording is English.
- System uses KS terminology.
- Fair allocation follows individual Minimum KS and Maximum KS.
- Emergency Reallocation does not rerun the main optimizer.
- Multiple emergency cases are appended into Emergency Log.
- Manual Fine Tuning allows human adjustment after the optimizer and updates the workload chart.


Emergency Replacement KS Rule
-----------------------------
For emergency replacement, KS is counted as full subject/class KS for every replaced class, not prorated by weeks. Example: if a replacement lecturer has 8 KS and replaces one 4-KS class, the new load becomes 12 KS; if replacing two 4-KS classes, the new load becomes 16 KS.


Emergency Reallocation update:
- Emergency Reason manual input is now required inside the system before running emergency reallocation.
- Emergency Reason remains editable in the Emergency Log before export.
- Replacement KS is counted as full subject/class KS per replaced class.


v5 Update:
- Emergency analysis now separates Temporary Cover and Emergency Replacement.
- Workload fairness is based on 14-week average semester load:
  Average Semester Load = (Week 1 + ... + Week 14) / 14.
- Temporary overload is visible through Peak Weekly Load and Temporary Overload Weeks.
- Emergency replacement can be split across two lecturers when one lecturer cannot cover the full KS.
- Lecturer Analysis now includes event notes for who covered whom, which weeks, and how many KS.
