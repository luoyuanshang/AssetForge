"""Explicit new-acquisition budgets; historical owner attempts remain immutable."""
import json
PROFILE='qa6k-rejection-sampling-5-to-10-v1'


def command_args(lane, *, first_pass_only=False):
    path=lane/'owner.json'
    if path.exists():
        old=json.loads(path.read_text())
        result=['--max-attempts',str(old.get('max_attempts',3))]
        if old.get('rs_budget_profile'):result+=['--rs-budget-profile',old['rs_budget_profile']]
        return result
    return ['--max-attempts','1'] if first_pass_only else ['--max-attempts','10','--rs-budget-profile',PROFILE]


def limits(tasks, source):
    metadata={r['task_id']:r for r in source['tasks']}
    result={}
    for task in tasks:
        row=metadata[task['task_id']]
        scarce=(row.get('domain')=='hr' or len(row.get('scored_apps',[]))>=4
                or len((task.get('info') or {}).get('assertions') or [])>=12)
        result[task['task_id']]=10 if scarce else 5
    return result
