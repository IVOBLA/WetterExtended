import hydro_flood_ml as h

def test_hit_intervals_do_not_count_gap():
    intervals = h._hit_intervals([0,5,10,40,45,50], 5)
    assert len(intervals) == 2
    assert sum(i['duration_min'] for i in intervals) == 30
    assert sum(i['duration_min'] for i in intervals) != 55
