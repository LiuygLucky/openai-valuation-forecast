def needs_followup(state, settings, budget):
    return bool(
        state.critique
        and state.critique.recommended_followup_queries
        and state.information_gaps
        and state.iteration_count < settings.max_iterations
        and budget.search_calls < settings.max_search_calls
        and settings.max_llm_calls - budget.llm_calls >= 3  # extract, reason, critique
    )
