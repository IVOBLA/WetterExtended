import numpy as np
from object_tracking import update_tracking_memory, tracking_memory

def test_merge_lineage_smoke():
    tracking_memory.clear()
    hsv=np.zeros((200,200,3),dtype=np.uint8)
    c1=np.array([[[10,10]],[[30,10]],[[30,30]],[[10,30]]],dtype=np.int32)
    c2=np.array([[[40,10]],[[60,10]],[[60,30]],[[40,30]]],dtype=np.int32)
    update_tracking_memory(hsv,[c1,c2],[],"2026-01-01_00-00-00")
    c3=np.array([[[8,8]],[[62,8]],[[62,32]],[[8,32]]],dtype=np.int32)
    objs,_=update_tracking_memory(hsv,[c3],[],"2026-01-01_00-05-00")
    assert objs and objs[0].get("lineage")=="merged"
    assert len(objs[0].get("parents",[]))>=2
