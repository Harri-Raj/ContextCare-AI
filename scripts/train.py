"""Build 1500+ labelled samples, group-aware holdout and versioned intent model."""
import csv,sys,json,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from contextcare.nlp import IntentModel
from sklearn.pipeline import FeatureUnion,Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import classification_report,confusion_matrix,accuracy_score
import sklearn,joblib,numpy as np
random.seed(7)
subjects=['please','could you','hey','now','for me','today','tomorrow','when possible','this afternoon','quickly','for next week','if you can','at home','this evening','before dinner','at work','in the app','somehow','right now','this morning']
trails=['',' please',' now',' thanks',' for me',' if possible',' today',' soon',' in the app',' okay']
rows=[]
for label,examples in IntentModel.SEEDS.items():
    for group,base in enumerate(examples):
        for prefix in subjects:
            for trail in trails[:5]:
                value=f'{prefix} {base}{trail}' if prefix not in ('hey','please') else f'{prefix}, {base}{trail}'
                rows.append({'text':value,'intent':label,'group':f'{label}:{group}'})
random.shuffle(rows)
(ROOT/'data').mkdir(exist_ok=True)
with (ROOT/'data/intents.csv').open('w',newline='',encoding='utf8') as f:
    w=csv.DictWriter(f,fieldnames=['text','intent','group']);w.writeheader();w.writerows(rows)
X=[r['text'] for r in rows];Y=[r['intent'] for r in rows];G=[r['group'] for r in rows]
outer=GroupShuffleSplit(n_splits=1,test_size=.20,random_state=42)
train_idx,test_idx=next(outer.split(X,Y,G))
vector=FeatureUnion([('words',TfidfVectorizer(ngram_range=(1,2),sublinear_tf=True)),('chars',TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5),min_df=2,sublinear_tf=True))])
pipeline=Pipeline([('features',vector),('classifier',LogisticRegression(max_iter=700))]);pipeline.fit([X[i] for i in train_idx],[Y[i] for i in train_idx])
pred=pipeline.predict([X[i] for i in test_idx]);truth=[Y[i] for i in test_idx]
report=classification_report(truth,pred,output_dict=True,zero_division=0)
(ROOT/'models').mkdir(exist_ok=True);joblib.dump({'sklearn':sklearn.__version__,'model':pipeline},ROOT/'models/intent.joblib')
(ROOT/'reports').mkdir(exist_ok=True)
(ROOT/'reports/intent_metrics.json').write_text(json.dumps({'samples':len(rows),'train':len(train_idx),'test':len(test_idx),'holdout':'group-aware by seed template, not a real-world benchmark','accuracy':accuracy_score(truth,pred),'macro_f1':report['macro avg']['f1-score'],'classification_report':report},indent=2))
try:
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=sorted(set(truth)|set(pred));cm=confusion_matrix(truth,pred,labels=labels)
    fig,ax=plt.subplots(figsize=(12,10));ax.imshow(cm);ax.set_xticks(range(len(labels)),labels,rotation=90,fontsize=7);ax.set_yticks(range(len(labels)),labels,fontsize=7);ax.set_title('Intent confusion matrix (group-aware synthetic holdout)');fig.tight_layout();fig.savefig(ROOT/'reports/confusion_matrix.png',dpi=140);plt.close(fig)
    probs=pipeline.predict_proba([X[i] for i in test_idx]);conf=np.max(probs,axis=1)
    coverage=[]
    for t in np.arange(.1,.91,.1):
        accept=conf>=t
        coverage.append([round(float(t),2),round(float(accept.mean()),3),round(float(np.mean(pred[accept]==np.array(truth)[accept])),3) if accept.any() else None])
    (ROOT/'reports/threshold_coverage.json').write_text(json.dumps(coverage,indent=2))
except ImportError:pass
print('Trained:',len(rows),'rows; group-disjoint holdout accuracy:',round(accuracy_score(truth,pred),3))
