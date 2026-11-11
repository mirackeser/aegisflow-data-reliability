# SPDX-License-Identifier: Apache-2.0
"""Frozen, provider-neutral acceptance policy; compute counts instead of trusting rates."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from .core import BenchmarkError, LABELS, PREDICTIONS, ID, canonical, closed, parse, validate

HASH={'type':'string','pattern':'^[0-9a-f]{64}$','minLength':64,'maxLength':64}
CASES={'type':'array','minItems':1,'maxItems':10000,'items':closed({'case_id':ID,'family':ID,'label':{'enum':list(LABELS)}})}
OUTPUTS={'type':'array','minItems':1,'maxItems':10000,'items':closed({'case_id':ID,'prediction':{'enum':list(PREDICTIONS)},'unsupported_claim':{'type':'boolean'}})}
POLICY=closed({key:{'type':'integer','minimum':1,'maximum':10000} for key in
    ('min_cases','min_class_support','min_family_support','min_accuracy_bps','min_precision_bps','min_recall_bps','min_family_accuracy_bps')})
PROTOCOL=closed({'version':{'const':'1'},'dataset_sha256':HASH,'model_revision_sha256':HASH,'policy':POLICY,
    'families':{'type':'array','minItems':1,'maxItems':64,'uniqueItems':True,'items':ID},
    **{key:{'type':'boolean'} for key in ('independent_labels','sealed','leakage_checked','independent_claim_review')}})


@dataclass(frozen=True)
class QualityPolicy:
    min_cases: int=1000
    min_class_support: int=100
    min_family_support: int=30
    min_accuracy_bps: int=9500
    min_precision_bps: int=9500
    min_recall_bps: int=9500
    min_family_accuracy_bps: int=9500

    def __post_init__(self):
        validate(POLICY,asdict(self))
        if any(type(value) is not int for value in asdict(self).values()):
            raise BenchmarkError('Integer quality policy required')


def freeze_protocol(cases, *, model_revision_sha256, families, policy=QualityPolicy(),
                    independent_labels=False, sealed=False, leakage_checked=False, independent_claim_review=False):
    """Predeclare before evaluation; provenance flags require trusted host attestation."""
    if type(policy) is not QualityPolicy or type(families) is not tuple:
        raise BenchmarkError('Trusted quality protocol required')
    value=parse(cases)
    validate(CASES,value)
    if len({item['case_id'] for item in value}) != len(value):
        raise BenchmarkError('Duplicate quality case')
    protocol={'version':'1','dataset_sha256':sha256(cases).hexdigest(),'model_revision_sha256':model_revision_sha256,
        'policy':asdict(policy),'families':list(families),'independent_labels':independent_labels,
        'sealed':sealed,'leakage_checked':leakage_checked,'independent_claim_review':independent_claim_review}
    validate(PROTOCOL,protocol)
    return canonical(protocol)


def evaluate_quality(protocol_bytes, cases_bytes, predictions_bytes, *, model_revision_sha256):
    """Acceptance for this dataset/model/policy only. No deployment or authentication."""
    protocol=parse(protocol_bytes)
    validate(PROTOCOL,protocol)
    cases,outputs=parse(cases_bytes),parse(predictions_bytes)
    validate(CASES,cases)
    validate(OUTPUTS,outputs)
    if (protocol['dataset_sha256'] != sha256(cases_bytes).hexdigest()
            or protocol['model_revision_sha256'] != model_revision_sha256):
        raise BenchmarkError('Quality protocol binding rejected')
    ids={item['case_id'] for item in cases}
    indexed={item['case_id']:item for item in outputs}
    if len(ids)!=len(cases) or len(indexed)!=len(outputs) or ids!=set(indexed):
        raise BenchmarkError('Exact quality case coverage required')
    policy=QualityPolicy(**protocol['policy'])
    rejected=[]
    def require(condition, code):
        if not condition:rejected.append(code)
    def meets(correct,total,threshold):
        return total>0 and correct*10000>=total*threshold
    require(all(protocol[key] for key in ('independent_labels','sealed','leakage_checked','independent_claim_review')),'PROVENANCE_NOT_APPROVED')
    require(len(cases)>=policy.min_cases,'INSUFFICIENT_CASES')
    require({item['family'] for item in cases}==set(protocol['families']),'FAMILY_COVERAGE_MISMATCH')
    correct=sum(indexed[item['case_id']]['prediction']==item['label'] for item in cases)
    abstentions=sum(item['prediction']=='ABSTAIN' for item in outputs)
    errors=sum(item['prediction']=='ERROR' for item in outputs)
    unsupported=sum(item['unsupported_claim'] for item in outputs)
    require(meets(correct,len(cases),policy.min_accuracy_bps),'ACCURACY_BELOW_TARGET')
    require(errors==0,'EXECUTION_ERRORS')
    require(unsupported==0,'UNSUPPORTED_CLAIMS')
    classes={}
    for label in LABELS:
        support=sum(item['label']==label for item in cases)
        predicted=sum(item['prediction']==label for item in outputs)
        tp=sum(item['label']==label and indexed[item['case_id']]['prediction']==label for item in cases)
        classes[label]={'support':support,'predicted':predicted,'true_positive':tp}
        require(support>=policy.min_class_support,'CLASS_SUPPORT:'+label)
        require(meets(tp,predicted,policy.min_precision_bps),'CLASS_PRECISION:'+label)
        require(meets(tp,support,policy.min_recall_bps),'CLASS_RECALL:'+label)
    families={}
    for family in protocol['families']:
        selected=[item for item in cases if item['family']==family]
        matched=sum(indexed[item['case_id']]['prediction']==item['label'] for item in selected)
        families[family]={'support':len(selected),'correct':matched}
        require(len(selected)>=policy.min_family_support,'FAMILY_SUPPORT:'+family)
        require(meets(matched,len(selected),policy.min_family_accuracy_bps),'FAMILY_ACCURACY:'+family)
    return {'version':'1','decision':'PASS' if not rejected else 'BLOCK','reasons':rejected,
        'protocol_sha256':sha256(protocol_bytes).hexdigest(),'dataset_sha256':protocol['dataset_sha256'],
        'predictions_sha256':sha256(predictions_bytes).hexdigest(),'model_revision_sha256':model_revision_sha256,
        'case_count':len(cases),'correct':correct,'abstentions':abstentions,'errors':errors,
        'unsupported_claims':unsupported,'per_class':classes,'families':families}
