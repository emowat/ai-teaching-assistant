#test_run.py

#run the whole eval pipeline
#grades files from test_data to test_results


import sys, types, json, random
from prompts import macro_metrics, micro_metrics

random.seed(42)
ALL_METRICS= list(set(macro_metrics+micro_metrics))

class Reply:
  def __init__(self, text):
    self.content= text
class Judge:
  def __init__(self, **Kwargs):
    pass
  def batch(self, prompts, config=None, return_exceptions=True):
    answers=[]
    for _ in prompts:
      scores={}
      for metric in ALL_METRICS:
        
        scores[metric] = random.choice(["1", "1", "0", "NA"])
        scores[metric + "_reason"]= "test"
      answers.append(Reply(json.dumps(scores)))
    return answers
  
#make from landchain_openai import ChatOpenAI hand back fake judge
fake= types.ModuleType("langchain_openai")
fake.ChatOpenAI= Judge
sys.modules["langchain_openai"]=fake

#point eval to the test folder and run it
import run_eval
run_eval.EVAL_DIR="test_data"
run_eval.RESULTS_DIR= "test_results"
run_eval.DATASET_NAME= "eval_log"
run_eval.OPENAI_API_KEY="not_needed"
run_eval.main()

print("done, open test_results")
print("pass rates are fake since judge is fake")