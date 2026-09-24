"""JSON transport repair for demonstrated native integer assignments.

Initial task validation remains strict. This
helper is intended only for snapshots created by the pinned native API, never
for arbitrary Author inputs. It preserves integer values, not string coercion.
"""
import copy

CONTRACT='native-live-integer-assignment-snapshot-transport-v2'
MAILCHIMP_CONTRACT='native-live-integer-and-mailchimp-note-snapshot-transport-v3'
ALLOWED_PATHS={('freshdesk','tickets','responder_id'),('freshdesk','tickets','group_id'),
               ('helpscout','conversations','mailbox_id')}

def restore_native_snapshot(world_type, snapshot, *, contract=CONTRACT):
    if contract not in (CONTRACT, MAILCHIMP_CONTRACT):
        raise ValueError('unrecognized native snapshot transport contract')
    from pydantic import ValidationError
    value=copy.deepcopy(snapshot)
    try:return world_type(**value)
    except ValidationError as original:
        errors=original.errors();repairs=[];note_repairs=[]
        for error in errors:
            path=error['loc']
            if (contract==MAILCHIMP_CONTRACT and error['type']=='string_type'
                    and len(path)==5 and path[:2]==('mailchimp','subscribers')
                    and path[3]=='notes' and type(path[2]) is int and type(path[4]) is int):
                notes=value[path[0]][path[1]][path[2]][path[3]]
                note=notes[path[4]]
                if type(note) is not dict or set(note)!={'note'} or type(note['note']) is not str:
                    raise original
                note_repairs.append((path,note));notes[path[4]]=''
                continue
            if (error['type']!='string_type' or len(path)!=4
                    or (path[0],path[1],path[3]) not in ALLOWED_PATHS
                    or type(path[2]) is not int):
                raise original
            parent=value[path[0]][path[1]][path[2]];number=parent[path[3]]
            if type(number) is not int:raise original
            repairs.append((path,number));parent[path[3]]=str(number)
        # Validate every other property, construct the exact official model
        # classes, then restore precisely the values that native assignment kept.
        world=world_type(**value)
        for path,number in repairs:
            target=getattr(getattr(world,path[0]),path[1])[path[2]]
            setattr(target,path[3],number)
        for path,note in note_repairs:
            world.mailchimp.subscribers[path[2]].notes[path[4]]=note
        return world
