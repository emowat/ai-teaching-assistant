# -*- coding: utf-8 -*-
"""
run_ta.py
This is the file that makes the TA effectivenes slide figures. Loads from judge results saves a csv and bar chart.

"""

import os
import eval_functions as ef


RESULTS_DIR = os.environ.get("RESULTS_DIR", "evaluation/model_eval_results/turn_log_results_7232026") #input 
OUTPUT_DIR = os.environ.get("OUTPUT", RESULTS_DIR) #save visuals 
PRIMARY= os.environ.get("PRIMARY", "bedrock_claude_haiku") #judge to show in main slide

def main ():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ef.results_dir=OUTPUT_DIR
    
    #build values
    df= ef.build_ta_effectiveness(RESULTS_DIR)
    if len(df)==0:
        print( "no judge folders found", RESULTS_DIR); return
    print(df.to_string(index= False))
    
    #save csv of results    
    csv_path= os.path.join(OUTPUT_DIR, "TA_effectiveness_appendix.csv")
    df.to_csv(csv_path, index= False)
    print("saved ", csv_path)
    
    #metrics used in slides
    slide= ef.build_main_slide(RESULTS_DIR, PRIMARY)
    _path= os.path.join(OUTPUT_DIR, "main_slide_metrics.csv") 
    slide.to_csv(_path, index= False)
    print("saved", _path)   
    
    
    #make visual
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt
        def _savefig(*a, **k):
            _savefig.n +=1
            _plt.savefig(os.path.join(OUTPUT_DIR, f"TA_effectiveness_chart_{_savefig.n}.png")); _plt.close()
        _savefig.n=0
        if ef.plt is not None: ef.plt.show= _savefig    
        ef.plot_ta_effectiveness(df, "TA EFFECTIVENESS BY JUDGE")
        print("saved", _savefig.n, "Chart PNG to", OUTPUT_DIR)
        
        #plot of single judge results
        cats=ef.build_ta_cats(RESULTS_DIR, PRIMARY)
        
        ef.plat_ta_cats(cats, "Claude Haiku 4.5 Evaluation By Category")
        print("saved", _savefig.n, "Chart PNG to", OUTPUT_DIR)
        
    except Exception as _e:
        print("skipped visual", _e)
    
    

if __name__ == "__main__":
    main()
