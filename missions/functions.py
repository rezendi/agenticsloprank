def get_openai_functions():
    return [
        get_file_selector_tool(),
        get_pr_selector_tool(),
        get_issue_estimator_tool(),
        get_detective_report_tool(),
    ]


def get_openai_functions_for(tool_key):
    if tool_key == "data_check":
        return [get_data_check_tool()]
    if tool_key == "files":
        return [get_file_selector_tool()]
    if tool_key == "pulls":
        return [get_pr_selector_tool()]
    if tool_key == "issues":
        return [get_issue_estimator_tool()]
    if tool_key == "detective_report":
        return [get_detective_report_tool()]
    if tool_key == "perform_rating":
        return [get_rating_tool()]
    if tool_key == "analyze_risks":
        return [get_analyze_risks_tool()]
    if tool_key == "assess_risks":
        return [get_assess_risks_tool()]
    if tool_key == "identify_issue":
        return [get_identify_issue_tool()]
    return get_openai_functions()


def get_data_check_tool():
    data_check_tool = {
        "type": "function",
        "function": {
            "name": "data_check",
            "description": "Given a list of factual assertions from a report, and the report's source data, indicate which assertions are supported by the data and where.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "assertions": {
                        "type": "array",
                        "description": "A list of indications whether a factual assertion is supported by the data",
                        "items": {
                            "type": "object",
                            "properties": {
                                "assertion": {
                                    "type": "string",
                                    "description": "A very brief summary of the assertion",
                                },
                                "supported": {
                                    "type": "boolean",
                                    "description": "Whether the assertion is supported by the data",
                                },
                                "factual": {
                                    "type": "boolean",
                                    "description": "Indicates whether the assertion is a concrete, binary fact, or a more subjective judgment",
                                },
                                "support": {
                                    "type": "string",
                                    "description": "The title, identifier, or other very brief description of the part of the data which supports the assertion",
                                },
                            },
                            "required": [
                                "assertion",
                                "supported",
                                "factual",
                                "support",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["assertions"],
                "additionalProperties": False,
            },
        },
    }
    return data_check_tool


def get_file_selector_tool():
    file_selector_tool = {
        "type": "function",
        "function": {
            "name": "get_files",
            "description": "Fetch a list of source code files for further analysis",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {
                        "type": "array",
                        "description": "A list of files and the reasons they may be important",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "The name of the file",
                                },
                                "url": {
                                    "type": "string",
                                    "description": "The URL of the file",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "A brief explanation of why this file may be important",
                                },
                            },
                            "required": ["name", "url", "reason"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["files"],
                "additionalProperties": False,
            },
        },
    }
    return file_selector_tool


def get_pr_selector_tool():
    pr_selector_tool = {
        "type": "function",
        "function": {
            "name": "get_prs",
            "description": "Fetch a list of pull requests for detailed analysis",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "prs": {
                        "type": "array",
                        "description": "A list of pull requests and the reasons they may be significant",
                        "items": {
                            "type": "object",
                            "properties": {
                                "number": {
                                    "type": "number",
                                    "description": "The number of the pull request",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "A brief explanation of why this PR may be important",
                                },
                            },
                            "required": ["number", "reason"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["prs"],
                "additionalProperties": False,
            },
        },
    }
    return pr_selector_tool


def get_issue_estimator_tool():
    issue_estimator_tool = {
        "type": "function",
        "function": {
            "name": "estimate_issues",
            "description": "Estimate the size of, and amount of work remaining to do, for a Jira/Linear/GitHub issue",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "description": "A list of issues and their estimate size, remaining hours of work, and the rationale for the estimate",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {
                                    "type": "string",
                                    "description": "The identifier of the issue",
                                },
                                "size": {
                                    "type": "string",
                                    "description": "Relative size of the issue: one of XS, S, M, L, XL, XXL, XXXL",
                                },
                                "hours": {
                                    "type": "number",
                                    "description": "Absolute number of hours of work remaining to complete the issue, in hours, based on its size and the work done so far",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "A two- or three-sentence explanation of the rationale for the estimate",
                                },
                            },
                            "required": ["key", "size", "hours", "reason"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["issues"],
                "additionalProperties": False,
            },
        },
    }
    return issue_estimator_tool


def get_detective_report_tool():
    detective_report_tool = {
        "type": "function",
        "function": {
            "name": "detective_report",
            "description": "Iteratively assess and analyze a series of datasets to answer a question",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_assessment": {
                        "type": "string",
                        "description": "Analysis of the relevant aspects of the current dataset, to be appended to your previous analysis. This is the most important field in the report and should be several paragraphs long. Be terse and concise, but also thorough, detailed, and quantitative, and data-driven - no yapping and no speculation, that comes later.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "A brief explanation of why the next selected dataset may be important",
                    },
                    "next_data_type": {
                        "type": "string",
                        "description": "The type of the next data to fetch. This MUST be either 'file', 'dataset', or, if there seems to be no data left to fetch which seems likely to be important to your assessment, 'none'.",
                    },
                    "next_data_id": {
                        "type": "string",
                        "description": "The identifier of the next data to fetch. This MUST be either a dataset ID or a fully specified path to a file.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "A brief explanation of why this next data may be important.",
                    },
                    "estimated_significance": {
                        "type": "number",
                        "description": "The estimated significance of the next dataset, from 1 to 5",
                    },
                    "overall_summary": {
                        "type": "string",
                        "description": "A summary of the overall analysis to date",
                    },
                    "completion_indicator": {
                        "type": "boolean",
                        "description": "Whether the analysis is complete",
                    },
                },
                "required": [
                    "dataset_assessment",
                    "next_data_type",
                    "next_data_id",
                    "rationale",
                    "estimated_significance",
                    "overall_summary",
                    "completion_indicator",
                ],
                "additionalProperties": False,
            },
        },
    }
    return detective_report_tool


def get_rating_tool():
    rating_tool = {
        "type": "function",
        "function": {
            "name": "perform_rating",
            "description": "Rate the quality of an element or aspect of a software development project, such as a pull request or a Jira issue",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rating": {
                        "type": "number",
                        "description": "A numerical score from 1 to 5 inclusive which represents the quality of the item in question",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "A detailed explanation of the rationale for the rating",
                    },
                },
                "required": ["rating", "rationale"],
                "additionalProperties": False,
            },
        },
    }
    return rating_tool


def get_analyze_risks_tool():
    analyze_risks_tool = {
        "type": "function",
        "function": {
            "name": "analyze_risks",
            "description": "Iteratively assess and analyze a series of datasets and/or files to assess the risks a software project faces. Focus on the following risks: delivery, whether the project will achieve its goals; velocity, whether it is proceeding at a satisfactory pace; dependency, whether it relies on external systems or libraries that may fail; team, whether the team faces burnout, conflict, communication problems, or other issues; code quality, whether the code is well-written and maintainable; technical debt, whether the codebase is accumulating problems; test coverage, whether the project is well-tested; and error handling, whether errors are caught and reported.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_assessment": {
                        "type": "string",
                        "description": "Analysis of the current data, to be appended to your previous analysis. This analysis should inform assessments of the following risks: delivery, velocity, dependency, team, code quality, technical debt, test coverage, and error handling. This MUST be multiple paragraphs, but DO NOT mention any risks not addressed by this data. Be terse and concise, but also thorough, detailed, and quantitative, and data-driven - no yapping and no speculation, that comes later.",
                    },
                    "next_data_type": {
                        "type": "string",
                        "description": "The type of the next data to fetch. This MUST be either 'file', 'dataset', or, if there seems to be no data left to fetch which seems likely to be important to your assessment, 'none'.",
                    },
                    "next_data_id": {
                        "type": "string",
                        "description": "The identifier of the next data to fetch. This MUST be either a dataset ID or a fully specified path to a file.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "A brief explanation of why this next data may be important.",
                    },
                },
                "required": [
                    "dataset_assessment",
                    "next_data_type",
                    "next_data_id",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        },
    }
    return analyze_risks_tool


def get_assess_risks_tool():
    assess_risks_tool = {
        "type": "function",
        "function": {
            "name": "assess_risks",
            "description": "Assess the current risk levels of a software development project across several axes including delivery risks, velocity risks, team risks, dependency risks, code quality, technical debt, test coverage, and error handling. These risks must be assessed independently of one another.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "delivery_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the project may not hit its delivery targets",
                    },
                    "delivery_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the delivery risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "velocity_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the project's velocity may be slowing or even halting",
                    },
                    "velocity_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the velocity risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "dependency_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the project's dependencies may not be sufficient for its goals",
                    },
                    "dependency_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the dependency risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "team_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the project's team may not be able to deliver on its goals",
                    },
                    "team_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the delivery risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "code_quality_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the new code being checked in to the project be low-quality, difficult to maintain, buggy, or fraught with security flaws",
                    },
                    "code_quality_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the code quality risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "technical_debt_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the codebase sufferx from low code quality, bugginess, excessive complexity, security flaws, or other technical debt",
                    },
                    "technical_debt_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the technical debt risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "test_coverage_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the projct's automated testing is insufficient to catch bugs and regressions",
                    },
                    "test_coverage_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the test coverage risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                    "error_handling_risk_rating": {
                        "type": "number",
                        "description": "A score from 1 to 5 indicating the risk that the project's error handling is insufficient to catch and report errors",
                    },
                    "error_handling_rationale": {
                        "type": "string",
                        "description": "An explanation of the reasons for for the error handling risk rating. Cite specific issues or pull requests wbere possible.",
                    },
                },
                "required": [
                    "delivery_risk_rating",
                    "delivery_rationale",
                    "velocity_risk_rating",
                    "velocity_rationale",
                    "dependency_risk_rating",
                    "dependency_rationale",
                    "team_risk_rating",
                    "team_rationale",
                    "code_quality_risk_rating",
                    "code_quality_rationale",
                    "technical_debt_risk_rating",
                    "technical_debt_rationale",
                    "test_coverage_risk_rating",
                    "test_coverage_rationale",
                    "error_handling_risk_rating",
                    "error_handling_rationale",
                ],
                "additionalProperties": False,
            },
        },
    }
    return assess_risks_tool


def get_identify_issue_tool():
    identify_issue_tool = {
        "type": "function",
        "function": {
            "name": "identify_issue",
            "description": "Examine a collection of issue data and identify the single issue that is clearly most relevant to the text in question, if any.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rationale": {
                        "type": "string",
                        "description": "A brief explanation of why this issue is clearly the most relevant in this context, or why no issue seems to be relevant.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "An indicator of how confident you are that your response is correct, from 1 to 10.",
                    },
                    "issue_id": {
                        "type": "string",
                        "description": "The identifier of the issue that is clearly the most relevant in this context, or an empty string if no such issue is found.",
                    },
                },
                "required": [
                    "issue_id",
                    "confidence",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        },
    }
    return identify_issue_tool
