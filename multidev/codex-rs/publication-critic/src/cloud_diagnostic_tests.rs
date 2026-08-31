use super::*;
use pretty_assertions::assert_eq;

#[test]
fn scalar_contract_accepts_only_one_finite_in_domain_quality() {
    for (content, expected) in [
        (r#"{"quality":0}"#, Some(0.0)),
        (r#"{"quality":0.42}"#, Some(0.42)),
        (r#"{"quality":1}"#, Some(1.0)),
    ] {
        assert_eq!(
            parse_output(CloudDiagnosticTask::Scalar, content),
            expected.map(|quality| CloudDiagnosticOutput::Scalar { quality })
        );
    }

    for content in [
        r#"{"quality":-0.01}"#,
        r#"{"quality":1.01}"#,
        r#"{"quality":"0.42"}"#,
        r#"{"quality":0.42,"verdict":"PASS"}"#,
        r#"{"quality":0.1,"quality":0.2}"#,
        r#"0.42"#,
        r#"{"quality":0.42} trailing"#,
    ] {
        assert_eq!(parse_output(CloudDiagnosticTask::Scalar, content), None);
    }
}

#[test]
fn direct_gate_contract_accepts_only_exact_verdict_object() {
    assert_eq!(
        parse_output(CloudDiagnosticTask::DirectGate, r#"{"verdict":"PASS"}"#),
        Some(CloudDiagnosticOutput::DirectGate {
            verdict: CloudDiagnosticVerdict::Pass,
        })
    );
    assert_eq!(
        parse_output(CloudDiagnosticTask::DirectGate, r#"{"verdict":"REWRITE"}"#,),
        Some(CloudDiagnosticOutput::DirectGate {
            verdict: CloudDiagnosticVerdict::Rewrite,
        })
    );

    for content in [
        r#"{"verdict":"pass"}"#,
        r#"{"verdict":"FAIL"}"#,
        r#"{"verdict":"PASS","score":1}"#,
        r#"{"verdict":"PASS","explanation":"x"}"#,
        r#""PASS""#,
        r#"{"verdict":"PASS"} trailing"#,
    ] {
        assert_eq!(parse_output(CloudDiagnosticTask::DirectGate, content), None);
    }
}

#[test]
fn five_dimension_contract_is_exact_and_gate_is_non_compensating() {
    let pass = r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS"}"#;
    let fail = r#"{"useful_state_transfer":"PASS","honest_uncertainty":"FAIL","conditional_continuity":"PASS","scope_and_signal":"PASS","internal_consistency":"PASS"}"#;

    let Some(CloudDiagnosticOutput::FiveDimension { decisions }) =
        parse_output(CloudDiagnosticTask::FiveDimension, pass)
    else {
        panic!("valid five-dimension output was rejected");
    };
    assert_eq!(decisions.local_verdict(), CloudDiagnosticVerdict::Pass);

    let Some(CloudDiagnosticOutput::FiveDimension { decisions }) =
        parse_output(CloudDiagnosticTask::FiveDimension, fail)
    else {
        panic!("valid five-dimension output was rejected");
    };
    assert_eq!(decisions.local_verdict(), CloudDiagnosticVerdict::Rewrite);

    for content in [
        r#"{"useful_state_transfer":"N/A","honest_uncertainty":"PASS","conditional_continuity":"PASS","scope_and_signal":"PASS","internal_consistency":"PASS"}"#,
        r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS"}"#,
        r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS","gate":"PASS"}"#,
        r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS","confidence":1}"#,
        r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS","explanation":"x"}"#,
    ] {
        assert_eq!(
            parse_output(CloudDiagnosticTask::FiveDimension, content),
            None
        );
    }
}

#[test]
fn output_contracts_use_illegal_templates_instead_of_copyable_legal_values() {
    let scalar = system_message(CloudDiagnosticTask::Scalar);
    let direct = system_message(CloudDiagnosticTask::DirectGate);
    let five = system_message(CloudDiagnosticTask::FiveDimension);
    let (scalar_common, scalar_contract) = scalar
        .split_once("# Output contract\n\n")
        .expect("scalar contract");
    let (direct_common, direct_contract) = direct
        .split_once("# Output contract\n\n")
        .expect("direct contract");
    let (five_common, five_contract) = five
        .split_once("# Output contract\n\n")
        .expect("five-dimension contract");
    assert_eq!(scalar_common, direct_common);
    assert_eq!(scalar_common, five_common);
    assert!(scalar_common.contains("specific packet in the user message"));

    assert!(scalar_contract.contains(r#"{"quality":<number in [0,1]>}"#));
    assert!(!scalar_contract.contains(r#"{"quality":0.42}"#));
    assert_eq!(
        parse_output(
            CloudDiagnosticTask::Scalar,
            r#"{"quality":<number in [0,1]>}"#
        ),
        None
    );

    assert!(direct_contract.contains(r#"{"verdict":<PASS or REWRITE>}"#));
    assert!(!direct_contract.contains(r#"{"verdict":"PASS"}"#));
    assert!(!direct_contract.contains(r#"{"verdict":"REWRITE"}"#));
    assert_eq!(
        parse_output(
            CloudDiagnosticTask::DirectGate,
            r#"{"verdict":<PASS or REWRITE>}"#
        ),
        None
    );

    assert!(five_contract.contains(r#"{"useful_state_transfer":<PASS or FAIL>"#));
    assert!(!five_contract.contains(
        r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS"}"#
    ));
    assert_eq!(
        parse_output(
            CloudDiagnosticTask::FiveDimension,
            r#"{"useful_state_transfer":<PASS or FAIL>,"honest_uncertainty":<PASS or FAIL>,"conditional_continuity":<PASS, FAIL, or N/A>,"scope_and_signal":<PASS or FAIL>,"internal_consistency":<PASS or FAIL>}"#
        ),
        None
    );
}
