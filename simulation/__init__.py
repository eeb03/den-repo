"""
Physics simulation of GPR surveys (roadmap M1a: owned ground truth).

Every target in a simulated scene is known exactly by construction, which is
the one property no held real dataset has. That makes simulation the only
zero-cost source of scoreable truth, but it is SIMULATED truth: a model
trained or validated only here is a sim result, never a field result, and
every artifact says so in its own provenance.

Modules:
    scenario  -- the scene description and its gprMax input-file rendering
    truth     -- exact geometry plus predicted reflection travel times
    analysis  -- measuring a simulated B-scan against its truth
    run_gprmax -- the runner; the only module that imports gprMax, and only
                  inside the docker/gprmax image
"""
