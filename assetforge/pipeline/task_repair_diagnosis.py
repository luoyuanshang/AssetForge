"""Task-local diagnostic delivery is separate from the QA semantic decision."""
import re

BEGIN='TASK_LOCAL_REPAIR_BRIEF_BEGIN'
END='TASK_LOCAL_REPAIR_BRIEF_END'

def delivery(prompt, memo, decision):
    required=decision=='reject' and BEGIN in prompt and END in prompt
    matched=re.findall(re.escape(BEGIN)+r'\s*(.*?)\s*'+re.escape(END),memo,re.S)
    valid=(len(matched)==1 and bool(matched[0].strip()) and memo.count(BEGIN)==1 and memo.count(END)==1)
    return {'required':required,'passed':not required or valid,
            'status':'complete' if not required or valid else 'diagnosis_delivery_error',
            'semantic_decision_preserved':decision}
