.text
    cbz x0, missing_clock
    cmn x0, #4095
    b.cs missing_clock
    .inst E9_RETURN_ADR
    .inst E9_ORIGINAL_CALL
missing_clock:
    str xzr, [x19, #136]
    .inst E9_SKIP_BRANCH
