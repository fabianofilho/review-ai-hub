"""
Standalone script to seed the database with initial data.

This script is idempotent and can be run multiple times without creating
duplicate data. It seeds the following:

  1. PROBAST – global assessment instrument for prediction model studies
     (20 items across 4 domains: participants, predictors, outcome, analysis)
  2. CHARMS 2.0 – global extraction template for prediction model data
     (14 entity types, ~82 extraction fields)

Run from the project root:
    python -m backend.app.seed
"""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AsyncSessionLocal
from app.models.assessment import AssessmentInstrument, AssessmentItem
from app.models.extraction import (
    ExtractionEntityType,
    ExtractionField,
    ExtractionTemplateGlobal,
)

# ---------------------------------------------------------------------------
# Fixed UUIDs — never change; enable deterministic, repeatable deployments
# ---------------------------------------------------------------------------

_PROBAST_ID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_CHARMS_TEMPLATE_ID = UUID("000c0000-0000-0000-0000-000000000001")

_ET_PREDICTION_MODELS = UUID("000c0001-0000-0000-0000-000000000000")
_ET_SOURCE_OF_DATA = UUID("000c0002-0000-0000-0000-000000000000")
_ET_PARTICIPANTS = UUID("000c0003-0000-0000-0000-000000000000")
_ET_OUTCOME = UUID("000c0004-0000-0000-0000-000000000000")
_ET_CANDIDATE_PRED = UUID("000c0005-0000-0000-0000-000000000000")
_ET_SAMPLE_SIZE = UUID("000c0006-0000-0000-0000-000000000000")
_ET_MISSING_DATA = UUID("000c0007-0000-0000-0000-000000000000")
_ET_MODEL_DEV = UUID("000c0008-0000-0000-0000-000000000000")
_ET_FINAL_PREDICTORS = UUID("000c0009-0000-0000-0000-000000000000")
_ET_MODEL_PERF = UUID("000c000a-0000-0000-0000-000000000000")
_ET_MODEL_VALID = UUID("000c000b-0000-0000-0000-000000000000")
_ET_MODEL_RESULTS = UUID("000c000c-0000-0000-0000-000000000000")
_ET_MODEL_INTERP = UUID("000c000d-0000-0000-0000-000000000000")
_ET_MODEL_OBS = UUID("000c000e-0000-0000-0000-000000000000")

# Standard response level lists
_PROBAST_LEVELS = ["yes", "probably yes", "probably no", "no", "no information"]
_YES_NO_UNCLEAR = ["Yes", "No", "Unclear", "No information"]
_YES_NO_NI = ["Yes", "No", "No information"]
_YES_NO_NOTEVAL_NI = ["Yes", "No", "Not evaluated", "No information"]
_YES_NO_NOTAPP_NI = ["Yes", "No", "Not applicable", "No information"]


# ---------------------------------------------------------------------------
# PROBAST
# ---------------------------------------------------------------------------


async def seed_probast(session: AsyncSession) -> None:
    """Seeds the PROBAST instrument and its 20 items."""
    print("Seeding PROBAST instrument...")

    instrument = await session.get(AssessmentInstrument, _PROBAST_ID)
    if instrument:
        print("  PROBAST already exists — skipping.")
        return

    instrument = AssessmentInstrument(
        id=_PROBAST_ID,
        name="PROBAST",
        tool_type="PROBAST",
        version="1.0.0",
        mode="human",
        target_mode="per_model",
        is_active=True,
        aggregation_rules={"domains": ["participants", "predictors", "outcome", "analysis"]},
        schema_={},
    )
    session.add(instrument)

    items_data = [
        # (domain, code, question, sort_order)
        (
            "participants",
            "1.1",
            "Were appropriate data sources used, e.g. cohort, RCT or nested case-control study data?",
            0,
        ),
        (
            "participants",
            "1.2",
            "Were all inclusions and exclusions of participants appropriate?",
            1,
        ),
        (
            "predictors",
            "2.1",
            "Were predictors defined and assessed in a similar way for all participants?",
            2,
        ),
        (
            "predictors",
            "2.2",
            "Were predictor assessments made without knowledge of outcome data?",
            3,
        ),
        (
            "predictors",
            "2.3",
            "Are all predictors available at the time the model is intended to be used?",
            4,
        ),
        ("outcome", "3.1", "Was the outcome determined appropriately?", 5),
        ("outcome", "3.2", "Was a prespecified or standard outcome definition used?", 6),
        ("outcome", "3.3", "Were predictors excluded from the outcome definition?", 7),
        (
            "outcome",
            "3.4",
            "Was the outcome defined and determined in a similar way for all participants?",
            8,
        ),
        (
            "outcome",
            "3.5",
            "Was the outcome determined without knowledge of predictor information?",
            9,
        ),
        (
            "outcome",
            "3.6",
            "Was the time interval between predictor assessment and outcome determination appropriate?",
            10,
        ),
        ("analysis", "4.1", "Were there a reasonable number of participants with the outcome?", 11),
        (
            "analysis",
            "4.2",
            "Were continuous and categorical predictors handled appropriately?",
            12,
        ),
        ("analysis", "4.3", "Were all enrolled participants included in the analysis?", 13),
        ("analysis", "4.4", "Were participants with missing data handled appropriately?", 14),
        (
            "analysis",
            "4.5",
            "Was selection of predictors based on univariable analysis avoided?",
            15,
        ),
        (
            "analysis",
            "4.6",
            "Were complexities in the data (e.g. censoring, competing risks, sampling) accounted for appropriately?",
            16,
        ),
        (
            "analysis",
            "4.7",
            "Were relevant model performance measures evaluated appropriately?",
            17,
        ),
        (
            "analysis",
            "4.8",
            "Were model overfitting and optimism in model performance accounted for?",
            18,
        ),
        (
            "analysis",
            "4.9",
            "Do predictors and their assigned weights in the final model correspond to the results from the reported multivariable analysis?",
            19,
        ),
    ]

    for domain, code, question, sort in items_data:
        instrument.items.append(
            AssessmentItem(
                instrument_id=_PROBAST_ID,
                domain=domain,
                item_code=code,
                question=question,
                sort_order=sort,
                required=True,
                allowed_levels=_PROBAST_LEVELS,
            )
        )

    print(f"  Created PROBAST with {len(items_data)} items.")


# ---------------------------------------------------------------------------
# CHARMS 2.0
# ---------------------------------------------------------------------------


async def seed_charms(session: AsyncSession) -> None:
    """Seeds the CHARMS 2.0 template, 14 entity types, and ~82 fields."""
    print("Seeding CHARMS 2.0 template...")

    template = await session.get(ExtractionTemplateGlobal, _CHARMS_TEMPLATE_ID)
    if template:
        print("  CHARMS already exists — skipping.")
        return

    # ---- Template ----
    session.add(
        ExtractionTemplateGlobal(
            id=_CHARMS_TEMPLATE_ID,
            name="CHARMS",
            description="CHARMS Checklist for prediction model studies. All fields are specific per prediction model.",
            framework="CHARMS",
            version="1.0.0",
        )
    )

    # ---- Entity types (14) ----
    _et = [
        ExtractionEntityType(
            id=_ET_PREDICTION_MODELS,
            template_id=_CHARMS_TEMPLATE_ID,
            name="prediction_models",
            label="Prediction Models",
            description="Prediction models found in the article. Each model has its own sections and fields.",
            parent_entity_type_id=None,
            cardinality="many",
            sort_order=0,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_SOURCE_OF_DATA,
            template_id=_CHARMS_TEMPLATE_ID,
            name="source_of_data",
            label="Source of Data",
            description="Data source used in the study (CHARMS 1.1)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=1,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_PARTICIPANTS,
            template_id=_CHARMS_TEMPLATE_ID,
            name="participants",
            label="Participants",
            description="Participant information (CHARMS 2.1–2.8)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=2,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_OUTCOME,
            template_id=_CHARMS_TEMPLATE_ID,
            name="outcome_to_be_predicted",
            label="Outcome to be Predicted",
            description="Outcome variable to be predicted (CHARMS 3.1–3.7)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=3,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_CANDIDATE_PRED,
            template_id=_CHARMS_TEMPLATE_ID,
            name="candidate_predictors",
            label="Candidate Predictors",
            description="Candidate predictors assessed (CHARMS 4.1–4.6)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=4,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_SAMPLE_SIZE,
            template_id=_CHARMS_TEMPLATE_ID,
            name="sample_size",
            label="Sample Size",
            description="Sample size and events (CHARMS 5.1–5.3)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=5,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MISSING_DATA,
            template_id=_CHARMS_TEMPLATE_ID,
            name="missing_data",
            label="Missing Data",
            description="Missing data and handling (CHARMS 6.1–6.2)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=6,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MODEL_DEV,
            template_id=_CHARMS_TEMPLATE_ID,
            name="model_development",
            label="Model Development",
            description="Prediction model development (CHARMS 7.1–7.4)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=7,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_FINAL_PREDICTORS,
            template_id=_CHARMS_TEMPLATE_ID,
            name="final_predictors",
            label="Final Predictors",
            description="Final predictors included in the model (multiple allowed)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="many",
            sort_order=8,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MODEL_PERF,
            template_id=_CHARMS_TEMPLATE_ID,
            name="model_performance",
            label="Model Performance",
            description="Model performance: calibration, discrimination, overall, clinical utility (CHARMS 8.1–8.4)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=9,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MODEL_VALID,
            template_id=_CHARMS_TEMPLATE_ID,
            name="model_validation",
            label="Model Validation",
            description="Model validation (CHARMS 9.1–9.2)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=10,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MODEL_RESULTS,
            template_id=_CHARMS_TEMPLATE_ID,
            name="model_results",
            label="Results",
            description="Final model results (CHARMS 10.1–10.4)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=11,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MODEL_INTERP,
            template_id=_CHARMS_TEMPLATE_ID,
            name="model_interpretation",
            label="Interpretation",
            description="Interpretation of the presented model (CHARMS 11.1)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=12,
            is_required=False,
        ),
        ExtractionEntityType(
            id=_ET_MODEL_OBS,
            template_id=_CHARMS_TEMPLATE_ID,
            name="model_observations",
            label="Observations",
            description="Extraction process observations and additional information (CHARMS 12.1–12.2)",
            parent_entity_type_id=_ET_PREDICTION_MODELS,
            cardinality="one",
            sort_order=13,
            is_required=False,
        ),
    ]
    for et in _et:
        session.add(et)

    # ---- Fields ----
    def _f(
        eid: UUID,
        name: str,
        label: str,
        desc: str,
        ftype: str,
        sort: int,
        *,
        required: bool = True,
        allowed: list[str] | None = None,
        unit: str | None = None,
        llm: str | None = None,
    ) -> ExtractionField:
        return ExtractionField(
            entity_type_id=eid,
            name=name,
            label=label,
            description=desc,
            field_type=ftype,
            sort_order=sort,
            is_required=required,
            allowed_values=allowed,
            unit=unit,
            llm_description=llm,
        )

    fields = [
        # --- prediction_models (2) ---
        _f(
            _ET_PREDICTION_MODELS,
            "model_name",
            "Model Name",
            "Name or identifier of the prediction model (CHARMS 0.5)",
            "text",
            0,
            llm="Extract the name or identifier of the prediction model. If multiple models are presented, extract each separately.",
        ),
        _f(
            _ET_PREDICTION_MODELS,
            "modelling_method",
            "Modelling Method",
            "Statistical modelling method used (CHARMS 7.1)",
            "select",
            1,
            allowed=[
                "Logistic regression",
                "Cox regression",
                "Linear regression",
                "Poisson regression",
                "Random forest",
                "Neural network",
                "Support vector machine",
                "No information",
            ],
            llm="Extract the statistical modelling method used to develop the prediction model (e.g., logistic regression, Cox regression).",
        ),
        # --- source_of_data (1) ---
        _f(
            _ET_SOURCE_OF_DATA,
            "data_source",
            "Source of Data",
            "Data source used in the study (CHARMS 1.1)",
            "select",
            0,
            allowed=[
                "Prospective cohort",
                "Retrospective cohort",
                "Case-control",
                "Case series",
                "RCT",
                "Registry",
                "No information",
            ],
            llm="Extract the source of data used in the study.",
        ),
        # --- participants (12) ---
        _f(
            _ET_PARTICIPANTS,
            "recruitment_method",
            "Recruitment Method",
            "Method used to recruit participants (CHARMS 2.1)",
            "select",
            0,
            allowed=[
                "Consecutive patients",
                "Random sampling",
                "Convenience sampling",
                "Stratified sampling",
                "No information",
            ],
            llm="Extract the method used to recruit participants into the study.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "recruitment_dates",
            "Recruitment Dates",
            "Recruitment period (CHARMS 2.2)",
            "text",
            2,
            llm="Extract the dates or time period during which participants were recruited.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "study_setting",
            "Study Setting",
            "Study setting or environment (CHARMS 2.3)",
            "text",
            3,
            llm="Extract the setting where the study was conducted (e.g., primary care, secondary care).",
        ),
        _f(
            _ET_PARTICIPANTS,
            "study_sites_regions",
            "Study Sites (Regions)",
            "Geographical regions of the study (CHARMS 2.4)",
            "text",
            4,
            llm="Extract the geographical regions or locations where the study was conducted.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "study_sites_number",
            "Study Sites (Number of Centers)",
            "Number of study centers (CHARMS 2.5)",
            "number",
            5,
            unit="centers",
            llm="Extract the number of centers or sites where the study was conducted.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "inclusion_criteria",
            "Inclusion Criteria",
            "Participant inclusion criteria (CHARMS 2.6)",
            "text",
            6,
            llm="Extract the criteria used to include participants in the study.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "exclusion_criteria",
            "Exclusion Criteria",
            "Participant exclusion criteria (CHARMS 2.7)",
            "text",
            7,
            llm="Extract the criteria used to exclude participants from the study.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "age_of_participants",
            "Age of Participants",
            "Age of participants (CHARMS 2.8.1)",
            "text",
            8,
            llm="Extract the age of participants. Include mean (SD), median (IQR), or range as reported.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "native_valve_endocarditis",
            "Native Valve Endocarditis",
            "Participants with native valve endocarditis (CHARMS 2.8.2)",
            "text",
            9,
            llm="Extract the number and percentage of participants with native valve endocarditis n (%).",
        ),
        _f(
            _ET_PARTICIPANTS,
            "valve_affected",
            "Valve Affected",
            "Affected valves (CHARMS 2.8.3)",
            "text",
            10,
            llm="Extract information about which valves were affected.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "characteristic_4",
            "Characteristic 4",
            "Additional participant characteristic 4 (CHARMS 2.8.4)",
            "text",
            11,
            llm="Extract additional participant characteristic 4 as reported in the study.",
        ),
        _f(
            _ET_PARTICIPANTS,
            "characteristic_5",
            "Characteristic 5",
            "Additional participant characteristic 5 (CHARMS 2.8.5)",
            "text",
            12,
            llm="Extract additional participant characteristic 5 as reported in the study.",
        ),
        # --- outcome_to_be_predicted (7) ---
        _f(
            _ET_OUTCOME,
            "outcome",
            "Outcome",
            "Outcome variable to be predicted (CHARMS 3.1)",
            "text",
            0,
            llm="Extract the outcome variable that the prediction model is designed to predict.",
        ),
        _f(
            _ET_OUTCOME,
            "outcome_definition",
            "Outcome Definition",
            "Precise definition of the outcome (CHARMS 3.2)",
            "text",
            1,
            llm="Extract the precise definition of the outcome variable.",
        ),
        _f(
            _ET_OUTCOME,
            "same_outcome_definition",
            "Same Outcome Definition for All Participants",
            "Same outcome definition for all participants? (CHARMS 3.3)",
            "select",
            2,
            allowed=_YES_NO_UNCLEAR,
            llm="Determine if the same outcome definition was used for all participants.",
        ),
        _f(
            _ET_OUTCOME,
            "type_of_outcome",
            "Type of Outcome",
            "Type of outcome (CHARMS 3.4)",
            "select",
            3,
            allowed=["Single", "Composite", "Time-to-event"],
            llm="Extract the type of outcome: single, composite, or time-to-event.",
        ),
        _f(
            _ET_OUTCOME,
            "outcome_assessed_blinded",
            "Outcome Assessed Blinded to Predictors",
            "Outcome assessed without knowledge of predictors? (CHARMS 3.5)",
            "select",
            4,
            allowed=_YES_NO_UNCLEAR,
            llm="Determine if the outcome was assessed without knowledge of predictor values.",
        ),
        _f(
            _ET_OUTCOME,
            "predictors_part_of_outcome",
            "Predictors Part of Outcome",
            "Candidate predictors part of the outcome definition? (CHARMS 3.6)",
            "select",
            5,
            allowed=_YES_NO_UNCLEAR,
            llm="Determine if any candidate predictors were part of the outcome definition.",
        ),
        _f(
            _ET_OUTCOME,
            "time_of_outcome",
            "Time of Outcome Occurrence",
            "Time point or period of outcome assessment (CHARMS 3.7)",
            "text",
            6,
            llm="Extract the time point or period when the outcome was assessed.",
        ),
        # --- candidate_predictors (6) ---
        _f(
            _ET_CANDIDATE_PRED,
            "number_of_candidates",
            "Number of Candidate Predictors",
            "Total candidate predictors assessed (CHARMS 4.1)",
            "number",
            0,
            unit="predictors",
            llm="Extract the total number of candidate predictors assessed for inclusion.",
        ),
        _f(
            _ET_CANDIDATE_PRED,
            "type_of_predictors",
            "Type of Predictors",
            "Type of candidate predictors (CHARMS 4.2)",
            "text",
            1,
            llm="Extract the type of candidate predictors assessed.",
        ),
        _f(
            _ET_CANDIDATE_PRED,
            "timing_of_measurement",
            "Timing of Predictors Measurement",
            "When predictors were measured (CHARMS 4.3)",
            "select",
            2,
            allowed=[
                "Pre-operative",
                "Post-operative",
                "At baseline",
                "During follow-up",
                "No information",
            ],
            llm="Extract when the candidate predictors were measured relative to the outcome.",
        ),
        _f(
            _ET_CANDIDATE_PRED,
            "predictors_definition_similar",
            "Predictors Definition Similar for All Participants",
            "Same predictor definition for all participants? (CHARMS 4.4)",
            "select",
            4,
            allowed=_YES_NO_UNCLEAR,
            llm="Determine if predictor definition and measurement were similar for all participants.",
        ),
        _f(
            _ET_CANDIDATE_PRED,
            "predictors_assessed_blinded",
            "Predictors Assessed Blinded for Outcome",
            "Predictors assessed without knowledge of outcome? (CHARMS 4.5)",
            "select",
            5,
            allowed=_YES_NO_UNCLEAR,
            llm="Determine if candidate predictors were assessed without knowledge of the outcome.",
        ),
        _f(
            _ET_CANDIDATE_PRED,
            "handling_continuous",
            "Handling of Continuous Predictors",
            "How continuous predictors were handled (CHARMS 4.6)",
            "select",
            6,
            allowed=[
                "Kept continuous",
                "Categorized",
                "Restricted cubic spline function",
                "No information",
            ],
            llm="Extract how continuous predictors were handled in the model.",
        ),
        # --- sample_size (3) ---
        _f(
            _ET_SAMPLE_SIZE,
            "number_of_participants",
            "Number of Participants",
            "Total participants in the study (CHARMS 5.1)",
            "number",
            0,
            unit="participants",
            llm="Extract the total number of participants included in model development.",
        ),
        _f(
            _ET_SAMPLE_SIZE,
            "number_of_events",
            "Number of Outcomes/Events",
            "Observed outcome events (CHARMS 5.2)",
            "number",
            1,
            unit="events",
            llm="Extract the number of outcome events that occurred in the study sample.",
        ),
        _f(
            _ET_SAMPLE_SIZE,
            "epv_epp",
            "Events Per Variable (EPV) or Per Parameter (EPP)",
            "EPV or EPP ratio (CHARMS 5.3)",
            "number",
            2,
            unit="events/variable",
            llm="Extract the EPV or EPP ratio, indicating sample size adequacy for model development.",
        ),
        # --- missing_data (2) ---
        _f(
            _ET_MISSING_DATA,
            "participants_with_missing",
            "Participants with Any Missing Value",
            "Participants with missing values (CHARMS 6.1)",
            "text",
            0,
            llm="Extract the number or percentage of participants with any missing values.",
        ),
        _f(
            _ET_MISSING_DATA,
            "handling_of_missing",
            "Handling of Missing Data",
            "How missing data were handled (CHARMS 6.2)",
            "select",
            1,
            allowed=[
                "Complete case analysis",
                "Multiple imputation",
                "Single imputation",
                "No information",
            ],
            llm="Extract how missing data were handled in the analysis.",
        ),
        # --- model_development (3) ---
        _f(
            _ET_MODEL_DEV,
            "selection_method_candidates",
            "Method for Selection of Candidate Predictors",
            "Method for selecting candidate predictors (CHARMS 7.2)",
            "select",
            0,
            allowed=[
                "Based on univariable associations",
                "Based on literature",
                "All candidates",
                "Clinical expertise",
                "No information",
            ],
            llm="Extract the method used to select candidate predictors for the multivariable model.",
        ),
        _f(
            _ET_MODEL_DEV,
            "selection_method_multivariable",
            "Method for Selection During Multivariable Modelling",
            "Predictor selection method during multivariable modelling (CHARMS 7.3)",
            "select",
            2,
            allowed=[
                "Backward elimination",
                "Forward selection",
                "Stepwise",
                "LASSO",
                "Ridge regression",
                "Elastic net",
                "Best subset",
                "No information",
            ],
            llm="Extract the method used to select predictors during multivariable model development.",
        ),
        _f(
            _ET_MODEL_DEV,
            "shrinkage",
            "Shrinkage of Predictor Weights",
            "Shrinkage applied to predictor weights or regression coefficients? (CHARMS 7.4)",
            "select",
            4,
            allowed=_YES_NO_NI,
            llm="Determine if shrinkage was applied to predictor weights or regression coefficients.",
        ),
        # --- final_predictors (2) ---
        _f(
            _ET_FINAL_PREDICTORS,
            "predictor_name",
            "Predictor Name",
            "Name of the final predictor included in the model",
            "text",
            0,
            llm="Extract the name of each final predictor included in the prediction model.",
        ),
        _f(
            _ET_FINAL_PREDICTORS,
            "predictor_weight",
            "Predictor Weight",
            "Weight, coefficient, or contribution of the predictor",
            "text",
            1,
            llm="Extract the weight, coefficient, or contribution of the predictor in the final model.",
        ),
        # --- model_performance — calibration (11) ---
        _f(
            _ET_MODEL_PERF,
            "calibration_plot",
            "Calibration Plot",
            "Calibration plot presented? (CHARMS 8.1.1)",
            "select",
            0,
            allowed=_YES_NO_NI,
            llm="Determine if a calibration plot was presented to assess model calibration.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_slope",
            "Calibration Slope",
            "Calibration slope reported? (CHARMS 8.1.2)",
            "select",
            1,
            allowed=_YES_NO_NI,
            llm="Determine if calibration slope was reported. If yes, extract the value and CI.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_slope_value",
            "Calibration Slope Value",
            "Calibration slope value",
            "number",
            2,
            llm="Extract the calibration slope value if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_slope_ci",
            "Calibration Slope (95% CI)",
            "95% CI of calibration slope",
            "text",
            3,
            llm="Extract the 95% confidence interval for calibration slope if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_in_large",
            "Calibration-in-the-Large (CITL)",
            "CITL reported? (CHARMS 8.1.3)",
            "select",
            4,
            allowed=_YES_NO_NI,
            llm="Determine if calibration-in-the-large (CITL) was reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_in_large_value",
            "Calibration-in-the-Large Value",
            "CITL value",
            "number",
            5,
            llm="Extract the calibration-in-the-large value if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_in_large_ci",
            "Calibration-in-the-Large (95% CI)",
            "95% CI of CITL",
            "text",
            6,
            llm="Extract the 95% confidence interval for calibration-in-the-large if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "hosmer_lemeshow",
            "Hosmer-Lemeshow Test",
            "Hosmer-Lemeshow test reported? (CHARMS 8.1.4)",
            "select",
            7,
            allowed=_YES_NO_NI,
            llm="Determine if Hosmer-Lemeshow test was reported. If yes, extract the p-value.",
        ),
        _f(
            _ET_MODEL_PERF,
            "hosmer_lemeshow_p_value",
            "Hosmer-Lemeshow Test (p-value)",
            "Hosmer-Lemeshow p-value",
            "text",
            8,
            llm="Extract the p-value from Hosmer-Lemeshow test if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_other",
            "Other Calibration Measures",
            "Other calibration measures reported? (CHARMS 8.1.5)",
            "select",
            9,
            allowed=_YES_NO_NI,
            llm="Determine if other calibration measures were reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "calibration_other_specify",
            "Other Calibration Measures (Specify)",
            "Specify other calibration measures",
            "text",
            10,
            llm="If 'Yes' for other calibration measures, extract the specific measures reported.",
        ),
        # --- model_performance — discrimination (12) ---
        _f(
            _ET_MODEL_PERF,
            "c_statistic",
            "C-Statistic",
            "C-statistic (AUC/ROC) reported? (CHARMS 8.2.1)",
            "select",
            11,
            allowed=_YES_NO_NI,
            llm="Determine if C-statistic (AUC/ROC) was reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "c_statistic_value",
            "C-Statistic Value",
            "C-statistic value",
            "number",
            12,
            llm="Extract the C-statistic value if reported (typically between 0 and 1).",
        ),
        _f(
            _ET_MODEL_PERF,
            "c_statistic_ci",
            "C-Statistic (95% CI)",
            "95% CI of C-statistic",
            "text",
            13,
            llm="Extract the 95% confidence interval for C-statistic if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "d_statistic",
            "D-Statistic",
            "D-statistic reported? (CHARMS 8.2.2)",
            "select",
            14,
            allowed=_YES_NO_NI,
            llm="Determine if D-statistic was reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "d_statistic_value",
            "D-Statistic Value",
            "D-statistic value",
            "number",
            15,
            llm="Extract the D-statistic value if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "d_statistic_ci",
            "D-Statistic (95% CI)",
            "95% CI of D-statistic",
            "text",
            16,
            llm="Extract the 95% confidence interval for D-statistic if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "auc_graph",
            "AUC Graph",
            "AUC/ROC graph presented? (CHARMS 8.2.3)",
            "select",
            17,
            allowed=_YES_NO_NI,
            llm="Determine if an AUC/ROC graph was presented.",
        ),
        _f(
            _ET_MODEL_PERF,
            "log_rank_test",
            "Log-Rank Test (if survival analysis)",
            "Log-rank test reported? (CHARMS 8.2.4)",
            "select",
            18,
            allowed=_YES_NO_NOTAPP_NI,
            llm="If survival analysis, determine if log-rank test was reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "log_rank_test_p_value",
            "Log-Rank Test (p-value)",
            "Log-rank test p-value",
            "text",
            19,
            llm="Extract the p-value from log-rank test if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "risk_group_curves",
            "Risk Group Curves (if survival analysis)",
            "Risk group curves presented? (CHARMS 8.2.5)",
            "select",
            20,
            allowed=_YES_NO_NOTAPP_NI,
            llm="If survival analysis, determine if risk group curves were presented.",
        ),
        _f(
            _ET_MODEL_PERF,
            "discrimination_other",
            "Other Discrimination Measures",
            "Other discrimination measures reported? (CHARMS 8.2.6)",
            "select",
            21,
            allowed=_YES_NO_NI,
            llm="Determine if other discrimination measures were reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "discrimination_other_specify",
            "Other Discrimination Measures (Specify)",
            "Specify other discrimination measures",
            "text",
            22,
            llm="If 'Yes' for other discrimination measures, extract the specific measures.",
        ),
        # --- model_performance — overall (8) ---
        _f(
            _ET_MODEL_PERF,
            "r_squared",
            "R-squared",
            "R-squared reported? (CHARMS 8.3.1)",
            "select",
            23,
            allowed=_YES_NO_NOTEVAL_NI,
            llm="Determine if R-squared was reported (e.g., Cox-Snell R², Nagelkerke R²).",
        ),
        _f(
            _ET_MODEL_PERF,
            "r_squared_value",
            "R-squared Value",
            "R-squared value",
            "number",
            24,
            llm="Extract the R-squared value if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "r_squared_ci",
            "R-squared (95% CI)",
            "95% CI of R-squared",
            "text",
            25,
            llm="Extract the 95% confidence interval for R-squared if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "r_squared_type",
            "R-squared Type",
            "Type of R-squared reported",
            "text",
            26,
            llm="Extract the type of R-squared reported (e.g., Cox-Snell R², Nagelkerke R²).",
        ),
        _f(
            _ET_MODEL_PERF,
            "brier_score",
            "Brier Score",
            "Brier score reported? (CHARMS 8.3.2)",
            "select",
            27,
            allowed=_YES_NO_NOTEVAL_NI,
            llm="Determine if Brier score was reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "brier_score_value",
            "Brier Score Value",
            "Brier score value",
            "number",
            28,
            llm="Extract the Brier score value if reported (between 0 and 1, lower is better).",
        ),
        _f(
            _ET_MODEL_PERF,
            "brier_score_ci",
            "Brier Score (95% CI)",
            "95% CI of Brier score",
            "text",
            29,
            llm="Extract the 95% confidence interval for Brier score if reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "overall_other",
            "Other Overall Measures",
            "Other overall performance measures? (CHARMS 8.3.3)",
            "select",
            30,
            allowed=_YES_NO_NI,
            llm="Determine if other overall performance measures were reported.",
        ),
        _f(
            _ET_MODEL_PERF,
            "overall_other_specify",
            "Other Overall Measures (Specify)",
            "Specify other overall measures",
            "text",
            31,
            llm="If 'Yes' for other overall measures, extract the specific measures reported.",
        ),
        # --- model_performance — clinical utility (3) ---
        _f(
            _ET_MODEL_PERF,
            "dca",
            "Decision Curve Analysis (DCA)",
            "DCA performed? (CHARMS 8.4.1)",
            "select",
            32,
            allowed=_YES_NO_NOTEVAL_NI,
            llm="Determine if Decision Curve Analysis (DCA) was performed.",
        ),
        _f(
            _ET_MODEL_PERF,
            "net_benefit",
            "Net Benefit",
            "Net benefit reported?",
            "select",
            33,
            allowed=_YES_NO_NI,
            llm="Determine if net benefit was reported as part of clinical utility assessment.",
        ),
        _f(
            _ET_MODEL_PERF,
            "clinical_utility_other",
            "Other Clinical Utility Measures",
            "Other clinical utility measures? (CHARMS 8.4)",
            "select",
            34,
            allowed=_YES_NO_NI,
            llm="Determine if other clinical utility measures were reported.",
        ),
        # --- model_validation (2) ---
        _f(
            _ET_MODEL_VALID,
            "validation_type",
            "Type of Validation",
            "Type of model validation performed (CHARMS 9.1)",
            "select",
            0,
            allowed=[
                "Internal validation",
                "External validation",
                "Both",
                "None",
                "No information",
            ],
            llm="Extract the type of model validation performed.",
        ),
        _f(
            _ET_MODEL_VALID,
            "validation_method",
            "Validation Method",
            "Method used for validation (CHARMS 9.2)",
            "select",
            1,
            allowed=[
                "Split-sample",
                "Cross-validation",
                "Bootstrap",
                "Temporal validation",
                "Geographical validation",
                "Incremental value",
                "No information",
            ],
            llm="Extract the method used for model validation.",
        ),
        # --- model_results (4) ---
        _f(
            _ET_MODEL_RESULTS,
            "formula_or_score",
            "Final Model Formula or Score",
            "Was the final model formula or score presented? (CHARMS 10.1)",
            "select",
            0,
            allowed=_YES_NO_NI,
            llm="Determine if the final model formula or score was presented.",
        ),
        _f(
            _ET_MODEL_RESULTS,
            "predictor_weights_included",
            "Final Model Included Predictor Weights or Regression Coefficients",
            "Predictor weights or coefficients included in the final model? (CHARMS 10.2)",
            "select",
            1,
            allowed=["Predictor weights", "Regression coefficients", "Both", "No information"],
            llm="Determine if the final model included predictor weights, regression coefficients, or both.",
        ),
        _f(
            _ET_MODEL_RESULTS,
            "intercept_included",
            "Final Model Included Intercept (or Baseline Survival)",
            "Intercept or baseline survival included? (CHARMS 10.3)",
            "select",
            2,
            allowed=["Yes", "No", "No information"],
            llm="Determine if the final model included an intercept or baseline survival.",
        ),
        _f(
            _ET_MODEL_RESULTS,
            "alternative_presentation",
            "Alternative Presentation of Final Model",
            "Alternative format for the final model? (CHARMS 10.4)",
            "select",
            3,
            allowed=[
                "Score system",
                "Nomogram",
                "Web calculator",
                "Mobile app",
                "None",
                "No information",
            ],
            llm="Extract if the final model was presented in an alternative format.",
        ),
        # --- model_interpretation (1) ---
        _f(
            _ET_MODEL_INTERP,
            "interpretation",
            "Interpretation of Presented Model",
            "Interpretation of the presented model (CHARMS 11.1)",
            "text",
            0,
            llm="Extract the interpretation or discussion of the presented prediction model.",
        ),
        # --- model_observations (2) ---
        _f(
            _ET_MODEL_OBS,
            "data_extraction_process",
            "Data Extraction Process",
            "Status of data extraction (CHARMS 12.1)",
            "select",
            0,
            allowed=[
                "All information has been successfully registered",
                "Some information missing",
                "Extraction incomplete",
            ],
            llm="Record the status of data extraction for this model.",
        ),
        _f(
            _ET_MODEL_OBS,
            "additional_information",
            "Additional Information",
            "Additional notes about the model or extraction process (CHARMS 12.2)",
            "text",
            1,
            llm="Extract any additional information or observations about the model or extraction process.",
        ),
    ]

    for field in fields:
        session.add(field)

    print(f"  Created CHARMS with 14 entity types and {len(fields)} fields.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    print("Starting database seeding process...")
    async with AsyncSessionLocal() as session:
        try:
            await seed_probast(session)
            await seed_charms(session)
            await session.commit()
            print("Seeding completed successfully.")
        except Exception as e:
            await session.rollback()
            print(f"Error: {e}")
            raise


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    asyncio.run(main())
