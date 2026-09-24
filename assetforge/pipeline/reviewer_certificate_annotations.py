"""Lossless rendering projection of known certificate labels and hard severity.

Only complete parenthesized annotations move out of machine labels. Original
memo lines and exact replacement spans are retained; no field is inferred.
"""
import re
from .construction_assets import require

LABELS=('frozen-runtime reproduction','Rubric gap','task repair suggestion','violated clause','evidence location')


def project(markdown, categories):
    edits=[]
    lines=markdown.splitlines(keepends=True)
    for i,line in enumerate(lines):
        text=line.rstrip('\r\n');ending=line[len(text):]
        prefix=r'([ \t]*(?:(?:[-*]|#{1,6})[ \t]+)?)'
        annotation=r'(?P<annotation>（[^（）\n]+）|\([^()\n]+\))'
        label=re.fullmatch(prefix+r'(?P<label>'+ '|'.join(map(re.escape,LABELS))+r')'+
            r'[ \t]*'+annotation+r'[ \t]*[:：](?P<body>.*)',text)
        if label:
            # Move commentary into this same field, not an unrelated paragraph.
            replacement=label[1]+label['label']+'：'+label['annotation']+label['body']+ending
        else:
            enum=re.fullmatch(prefix+r'(?P<label>severity|counterexample category)[ \t]*[:：][ \t]*'+
                r'(?P<value>[a-z_]+)[ \t]*'+annotation+r'[。.]?[ \t]*',text)
            if not enum:continue
            allowed={'hard'} if enum['label']=='severity' else set(categories)
            require(enum['value'] in allowed, 'annotation cannot choose an unknown enum')
            alternatives=set(categories)|{'hard','soft','minor'}
            require(not any(re.search(r'(?<![a-z_])'+re.escape(v)+r'(?![a-z_])',enum['annotation'])
                            for v in alternatives), 'ambiguous alternative enum annotation')
            # Keep the full annotated statement as ordinary adjacent prose.
            replacement=enum[1]+enum['label']+': '+enum['value']+'\n'+enum['label']+' note: '+enum['annotation']+ending
        edits.append({'line':i+1,'original':line,'projected':replacement})
        lines[i]=replacement
    require(edits, 'no supported unambiguous certificate annotation')
    return ''.join(lines), {'contract':'known-certificate-parenthetical-annotation-v1','edits':edits,
                           'semantic_content_retained':True,'decision_unchanged':True}


def restore(projected, annotation):
    # Exact inverse by stable ordered chunks; used for conservation verification.
    for edit in reversed(annotation['edits']):
        require(projected.count(edit['projected'])==1, 'ambiguous projected text')
        projected=projected.replace(edit['projected'],edit['original'],1)
    return projected
