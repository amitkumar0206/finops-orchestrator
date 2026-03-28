"""IaC analysis service for Terraform/CloudFormation uploads."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, cast
from uuid import uuid4

import structlog
import yaml

from backend.services.llm_service import llm_service

logger = structlog.get_logger(__name__)


_ALLOWED_EXTENSIONS = {
    ".tf",
    ".tfvars",
    ".hcl",
    ".yaml",
    ".yml",
    ".json",
}


_INSTANCE_SAVINGS_HINTS = {
    "m5.large": ("t3.large", 0.28),
    "m5.xlarge": ("t3.xlarge", 0.30),
    "m5.2xlarge": ("t3.2xlarge", 0.30),
    "c5.large": ("c6i.large", 0.20),
    "r5.large": ("r6i.large", 0.18),
}


@dataclass
class IacAnalysisRecord:
    analysis_id: str
    filename: str
    format: str
    original_content: str
    summary: str
    explanation: str
    pros: List[str]
    cons: List[str]
    cost_analysis: List[Dict[str, Any]]
    improved_content: str
    improvements: List[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    chat_history: List[Dict[str, str]] = field(default_factory=list)
    owner_user_id: Optional[str] = None
    owner_org_id: Optional[str] = None


class IacAnalysisService:
    """Handles IaC analysis workflows, chat, and improved template generation."""

    def __init__(self) -> None:
        self._records: Dict[str, IacAnalysisRecord] = {}

    @staticmethod
    def validate_filename(filename: str) -> None:
        lower = filename.lower()
        if not any(lower.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
            raise ValueError("Unsupported file type. Upload Terraform/HCL, YAML, or JSON IaC files.")

    @staticmethod
    def _detect_format(filename: str, content: str) -> str:
        lower = filename.lower()
        if lower.endswith((".tf", ".tfvars", ".hcl")):
            return "terraform"
        if lower.endswith((".yaml", ".yml")):
            return "cloudformation"
        if lower.endswith(".json"):
            stripped = content.lstrip()
            if stripped.startswith("{") and "AWSTemplateFormatVersion" in content:
                return "cloudformation"
            return "generic_json"
        if "resource \"aws_" in content:
            return "terraform"
        if "AWSTemplateFormatVersion" in content or "Resources:" in content:
            return "cloudformation"
        return "unknown"

    @staticmethod
    def _estimate_monthly_cost(service: str, config: str, amount: float) -> Dict[str, Any]:
        return {
            "service": service,
            "config": config,
            "estimated_monthly_cost_usd": round(amount, 2),
        }

    def _terraform_signals(self, content: str) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[str]]:
        pros: List[str] = []
        cons: List[str] = []
        cost: List[Dict[str, Any]] = []
        improvements: List[str] = []

        instance_types = re.findall(r'instance_type\s*=\s*"([a-zA-Z0-9.]+)"', content)
        for itype in instance_types:
            lowered = itype.lower()
            if lowered in _INSTANCE_SAVINGS_HINTS:
                target, ratio = _INSTANCE_SAVINGS_HINTS[lowered]
                cons.append(f"EC2 instance type `{itype}` appears over-provisioned for common workloads.")
                cost.append(self._estimate_monthly_cost("EC2", f"{itype} -> {target}", 120.0 * ratio))
                improvements.append(f"Downsize `{itype}` to `{target}` where CPU/Memory headroom permits.")

        if re.search(r"multi_az\s*=\s*true", content, flags=re.IGNORECASE):
            cons.append("RDS Multi-AZ is enabled; validate this is required outside production.")
            cost.append(self._estimate_monthly_cost("RDS", "Disable Multi-AZ in non-prod", 90.0))
            improvements.append("Use `multi_az = false` for dev/test databases.")
        else:
            pros.append("RDS Multi-AZ does not appear forced globally, helping lower non-prod spend.")

        if re.search(r'volume_type\s*=\s*"gp2"', content, flags=re.IGNORECASE):
            cons.append("EBS gp2 volume type detected; gp3 is typically 20% cheaper.")
            cost.append(self._estimate_monthly_cost("EBS", "gp2 -> gp3", 40.0))
            improvements.append("Switch EBS volume type from `gp2` to `gp3`.")

        if re.search(r"aws_s3_bucket", content) and not re.search(r"aws_s3_bucket_lifecycle_configuration", content):
            cons.append("S3 bucket resource detected without lifecycle policy resource.")
            cost.append(self._estimate_monthly_cost("S3", "Add lifecycle transitions", 55.0))
            improvements.append("Add an S3 lifecycle rule to transition old data to infrequent access/archive.")

        if re.search(r"aws_autoscaling_group", content):
            pros.append("Auto Scaling resources found, which is positive for elastic cost control.")

        if re.search(r"tags\s*=\s*\{", content):
            pros.append("Tag blocks found; this supports cost attribution and chargeback.")
        else:
            cons.append("Missing explicit tag blocks can reduce cost allocation quality.")
            improvements.append("Add standard tags: Environment, Owner, Project, CostCenter.")

        return pros, cons, cost, improvements

    def _cloudformation_signals(self, content: str) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[str]]:
        pros: List[str] = []
        cons: List[str] = []
        cost: List[Dict[str, Any]] = []
        improvements: List[str] = []

        try:
            template = cast(Dict[str, Any], yaml.safe_load(content) or {})
        except Exception:
            template = {}

        resources = cast(Dict[str, Any], template.get("Resources", {}) if isinstance(template, dict) else {})
        if not isinstance(resources, dict):
            resources = {}

        if not resources:
            cons.append("No CloudFormation Resources block was parsed; analysis confidence is reduced.")
            return pros, cons, cost, improvements

        for logical_id, resource in resources.items():
            if not isinstance(resource, dict):
                continue

            r_type = resource.get("Type", "")
            props = resource.get("Properties", {}) if isinstance(resource.get("Properties"), dict) else {}

            if r_type == "AWS::EC2::Instance":
                itype = str(props.get("InstanceType", ""))
                lowered = itype.lower()
                if lowered in _INSTANCE_SAVINGS_HINTS:
                    target, ratio = _INSTANCE_SAVINGS_HINTS[lowered]
                    cons.append(f"`{logical_id}` uses `{itype}`, often replaceable with `{target}`.")
                    cost.append(self._estimate_monthly_cost("EC2", f"{itype} -> {target}", 110.0 * ratio))
                    improvements.append(f"Review `{logical_id}` instance sizing against CloudWatch utilization.")

            if r_type == "AWS::RDS::DBInstance":
                if props.get("MultiAZ") is True:
                    cons.append(f"`{logical_id}` has MultiAZ=true; costly for non-production databases.")
                    cost.append(self._estimate_monthly_cost("RDS", "MultiAZ off in non-prod", 95.0))
                    improvements.append(f"Set `{logical_id}.Properties.MultiAZ` to `false` for dev/test.")

            if r_type == "AWS::S3::Bucket":
                lifecycle = props.get("LifecycleConfiguration")
                if not lifecycle:
                    cons.append(f"`{logical_id}` bucket has no lifecycle configuration.")
                    cost.append(self._estimate_monthly_cost("S3", "Lifecycle transitions", 65.0))
                    improvements.append(f"Add LifecycleConfiguration for `{logical_id}`.")
                else:
                    pros.append(f"`{logical_id}` includes lifecycle configuration.")

            if r_type == "AWS::AutoScaling::AutoScalingGroup":
                pros.append(f"`{logical_id}` uses AutoScaling, supporting dynamic cost control.")

        if template.get("Parameters"):
            pros.append("Template uses Parameters, improving reusability and environment-based sizing.")

        return pros, cons, cost, improvements

    async def _llm_enhance(
        self,
        fmt: str,
        filename: str,
        content: str,
        base_summary: str,
        base_explanation: str,
        pros: List[str],
        cons: List[str],
        cost_analysis: List[Dict[str, Any]],
        improvements: List[str],
    ) -> Tuple[str, str, List[str], List[str], List[Dict[str, Any]], List[str]]:
        llm = llm_service
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "explanation": {"type": "string"},
                "pros": {"type": "array", "items": {"type": "string"}},
                "cons": {"type": "array", "items": {"type": "string"}},
                "cost_analysis": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "service": {"type": "string"},
                            "config": {"type": "string"},
                            "estimated_monthly_cost_usd": {"type": "number"},
                        },
                        "required": ["service", "config", "estimated_monthly_cost_usd"],
                    },
                },
                "improvements": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "explanation", "pros", "cons", "cost_analysis", "improvements"],
        }

        prompt = (
            "You are an expert FinOps + IaC reviewer. Return concise, practical output.\n"
            f"File: {filename}\n"
            f"Format: {fmt}\n"
            f"Heuristic summary: {base_summary}\n"
            f"Heuristic explanation: {base_explanation}\n"
            f"Heuristic pros: {pros}\n"
            f"Heuristic cons: {cons}\n"
            f"Heuristic cost analysis: {cost_analysis}\n"
            f"Heuristic improvements: {improvements}\n"
            "Now improve these results with better wording and realistic but conservative monthly savings estimates."
        )

        structured = cast(Dict[str, Any], await llm.generate_structured_response(prompt=prompt, schema=schema, context={"max_tokens": 1200}))
        if structured.get("error"):
            return base_summary, base_explanation, pros, cons, cost_analysis, improvements

        def _string_list(value: Any, fallback: List[str]) -> List[str]:
            if not isinstance(value, list):
                return fallback
            parsed = [str(v).strip() for v in cast(List[Any], value) if str(v).strip()]
            return parsed[:8] or fallback

        llm_cost = structured.get("cost_analysis")
        if isinstance(llm_cost, list):
            safe_cost: List[Dict[str, Any]] = []
            for row in cast(List[Any], llm_cost)[:10]:
                if not isinstance(row, dict):
                    continue
                row_dict = cast(Dict[str, Any], row)
                try:
                    safe_cost.append(
                        {
                            "service": str(row_dict.get("service", "Unknown")),
                            "config": str(row_dict.get("config", "N/A")),
                            "estimated_monthly_cost_usd": round(float(row_dict.get("estimated_monthly_cost_usd", 0.0)), 2),
                        }
                    )
                except Exception:
                    continue
            if safe_cost:
                cost_analysis = safe_cost

        return (
            str(structured.get("summary", base_summary)),
            str(structured.get("explanation", base_explanation)),
            _string_list(structured.get("pros"), pros),
            _string_list(structured.get("cons"), cons),
            cost_analysis,
            _string_list(structured.get("improvements"), improvements),
        )

    @staticmethod
    def _apply_basic_improvements(content: str, fmt: str, improvements: List[str]) -> str:
        improved = content

        # Lightweight deterministic rewrites for demo usability.
        improved = re.sub(r'instance_type\s*=\s*"m5.large"', 'instance_type = "t3.large"', improved)
        improved = re.sub(r'instance_type\s*=\s*"m5.xlarge"', 'instance_type = "t3.xlarge"', improved)
        improved = re.sub(r'volume_type\s*=\s*"gp2"', 'volume_type = "gp3"', improved, flags=re.IGNORECASE)

        if fmt == "cloudformation":
            improved = re.sub(r'InstanceType:\s*m5.large', 'InstanceType: t3.large', improved)
            improved = re.sub(r'InstanceType:\s*m5.xlarge', 'InstanceType: t3.xlarge', improved)
            improved = re.sub(r'MultiAZ:\s*true', 'MultiAZ: false', improved)
            improved = re.sub(r'VolumeType:\s*gp2', 'VolumeType: gp3', improved, flags=re.IGNORECASE)

        header = "# Generated by FinOps Orchestrator IaC Workbench\n"
        if "generated by finops orchestrator" in improved.lower():
            return improved

        notes = "\n".join([f"# - {item}" for item in improvements[:5]])
        return f"{header}# Applied optimization notes:\n{notes}\n\n{improved}"

    def _extract_resource_identifiers(self, fmt: str, content: str) -> List[str]:
        """Extract stable resource identifiers for cross-file architecture insights."""
        if fmt == "terraform":
            return [f"{m[0]}.{m[1]}" for m in re.findall(r'resource\s+"([^"]+)"\s+"([^"]+)"', content)]

        if fmt == "cloudformation":
            try:
                template = cast(Dict[str, Any], yaml.safe_load(content) or {})
                resources = cast(Dict[str, Any], template.get("Resources", {}))
                return [str(key) for key in resources.keys()]
            except Exception:
                return []

        return []

    async def _cross_file_analysis(self, records: List[IacAnalysisRecord]) -> Dict[str, Any]:
        """Generate cross-file architecture insights from multiple IaC analyses."""
        if not records:
            return {
                "summary": "No files analyzed.",
                "architecture_observations": [],
                "risks": [],
                "recommendations": [],
                "total_estimated_monthly_savings": 0.0,
            }

        resource_to_files: Dict[str, List[str]] = {}
        file_regions: Dict[str, List[str]] = {}
        files_without_tags = 0

        all_cost_rows: List[Dict[str, Any]] = []
        format_counts: Dict[str, int] = {}

        for record in records:
            format_counts[record.format] = format_counts.get(record.format, 0) + 1
            all_cost_rows.extend(record.cost_analysis)

            content_lower = record.original_content.lower()
            if "tags" not in content_lower:
                files_without_tags += 1

            regions = re.findall(r'region\s*[:=]\s*"([a-z]{2}-[a-z]+-\d)"', record.original_content, flags=re.IGNORECASE)
            if regions:
                file_regions[record.filename] = sorted(set(regions))

            for resource_id in self._extract_resource_identifiers(record.format, record.original_content):
                resource_to_files.setdefault(resource_id, []).append(record.filename)

        duplicate_resources = [
            f"{resource} appears in {', '.join(files)}"
            for resource, files in resource_to_files.items()
            if len(files) > 1
        ]

        all_region_values = sorted({region for regions in file_regions.values() for region in regions})
        total_savings = round(sum(float(row.get("estimated_monthly_cost_usd", 0.0)) for row in all_cost_rows), 2)

        observations = [
            f"Analyzed {len(records)} files across formats: " + ", ".join(f"{k}={v}" for k, v in sorted(format_counts.items())),
            f"Detected {len(resource_to_files)} named resources across uploaded files.",
        ]
        if all_region_values:
            observations.append(f"Detected region references: {', '.join(all_region_values)}")

        risks: List[str] = []
        if duplicate_resources:
            risks.append("Potential duplicate/conflicting resource definitions across files.")
        if len(all_region_values) > 1:
            risks.append("Multiple regions detected across templates; verify intentional multi-region architecture.")
        if files_without_tags > 0:
            risks.append(f"{files_without_tags} file(s) appear to lack explicit tagging strategy.")
        if not risks:
            risks.append("No major cross-file risks detected by static heuristics.")

        recommendations = [
            "Consolidate shared variables (region, environment, tags) into common modules/parameters.",
            "Add a mandatory tag policy (Environment, Owner, Project, CostCenter) across all templates.",
            "Run plan/stack validation per environment before applying generated changes.",
        ]
        if duplicate_resources:
            recommendations.insert(0, "Review duplicate resource identifiers to avoid provisioning drift or conflicts.")

        summary = (
            f"Cross-file review completed for {len(records)} IaC files. "
            f"Estimated aggregate optimization potential is ${total_savings}/month."
        )

        # Optional LLM enhancement for better architecture narrative.
        try:
            llm_prompt = (
                "You are a principal cloud architect. Improve the cross-file architecture summary.\n"
                f"Current summary: {summary}\n"
                f"Observations: {observations}\n"
                f"Risks: {risks}\n"
                f"Recommendations: {recommendations}\n"
                "Return a concise improved summary in 2-3 sentences."
            )
            llm_summary = await llm_service.call_llm(prompt=llm_prompt, max_tokens=220)
            if llm_summary and len(llm_summary.strip()) > 20:
                summary = llm_summary.strip()
        except Exception:
            pass

        return {
            "summary": summary,
            "architecture_observations": observations,
            "risks": risks,
            "recommendations": recommendations,
            "duplicate_resource_details": duplicate_resources,
            "regions_detected": all_region_values,
            "total_estimated_monthly_savings": total_savings,
        }

    async def analyze_file(
        self,
        filename: str,
        content: str,
        owner_user_id: Optional[str] = None,
        owner_org_id: Optional[str] = None,
    ) -> IacAnalysisRecord:
        self.validate_filename(filename)

        fmt = self._detect_format(filename, content)

        if fmt == "terraform":
            pros, cons, cost, improvements = self._terraform_signals(content)
        elif fmt == "cloudformation":
            pros, cons, cost, improvements = self._cloudformation_signals(content)
        else:
            pros, cons, cost, improvements = [], [], [], []

        if not pros:
            pros = ["Template appears structured and parseable for additional review."]
        if not cons:
            cons = ["No major anti-patterns were automatically detected; validate utilization data before deployment."]
        if not cost:
            cost = [self._estimate_monthly_cost("General", "Baseline optimization opportunity", 35.0)]
        if not improvements:
            improvements = ["Add explicit tagging, lifecycle policies, and rightsizing guardrails."]

        estimated_total = round(sum(float(row.get("estimated_monthly_cost_usd", 0.0)) for row in cost), 2)
        summary = (
            f"Detected {fmt} template with {len(pros)} strengths and {len(cons)} cost risks. "
            f"Estimated optimization potential: ${estimated_total}/month."
        )
        explanation = (
            "This analysis combines static IaC heuristics with practical FinOps rules. "
            "For production confidence, validate proposed changes against workload utilization and SLO requirements."
        )

        try:
            summary, explanation, pros, cons, cost, improvements = await self._llm_enhance(
                fmt=fmt,
                filename=filename,
                content=content,
                base_summary=summary,
                base_explanation=explanation,
                pros=pros,
                cons=cons,
                cost_analysis=cost,
                improvements=improvements,
            )
        except Exception as err:
            logger.warning("iac_llm_enhancement_failed", error=str(err), filename=filename)

        improved_content = self._apply_basic_improvements(content, fmt, improvements)

        record = IacAnalysisRecord(
            analysis_id=str(uuid4()),
            filename=filename,
            format=fmt,
            original_content=content,
            summary=summary,
            explanation=explanation,
            pros=pros[:8],
            cons=cons[:8],
            cost_analysis=cost[:10],
            improvements=improvements[:10],
            improved_content=improved_content,
            owner_user_id=owner_user_id,
            owner_org_id=owner_org_id,
        )
        self._records[record.analysis_id] = record
        return record

    async def analyze_files(
        self,
        files: List[Tuple[str, str]],
        owner_user_id: Optional[str] = None,
        owner_org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze multiple IaC files and return per-file + cross-file architecture insights."""
        if not files:
            raise ValueError("At least one file is required")

        records: List[IacAnalysisRecord] = []
        for filename, content in files:
            record = await self.analyze_file(
                filename=filename,
                content=content,
                owner_user_id=owner_user_id,
                owner_org_id=owner_org_id,
            )
            records.append(record)

        cross_file = await self._cross_file_analysis(records)
        primary = records[0]
        return {
            "primary": primary,
            "records": records,
            "cross_file_analysis": cross_file,
            "file_count": len(records),
        }

    def get_record(self, analysis_id: str) -> Optional[IacAnalysisRecord]:
        return self._records.get(analysis_id)

    def assert_owner_access(
        self,
        analysis_id: str,
        user_id: Optional[str],
        org_id: Optional[str],
    ) -> IacAnalysisRecord:
        """Return record if the caller can access it, else raise an error."""
        record = self.get_record(analysis_id)
        if not record:
            raise ValueError("Analysis session not found")
        self._assert_owner(record, user_id, org_id)
        return record

    @staticmethod
    def _assert_owner(record: IacAnalysisRecord, user_id: Optional[str], org_id: Optional[str]) -> None:
        if record.owner_user_id and user_id and record.owner_user_id != user_id:
            raise PermissionError("You do not have access to this analysis session.")
        if record.owner_org_id and org_id and record.owner_org_id != org_id:
            raise PermissionError("You do not have access to this analysis session.")

    async def chat_about_template(
        self,
        analysis_id: str,
        question: str,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> str:
        record = self.get_record(analysis_id)
        if not record:
            raise ValueError("Analysis session not found")

        self._assert_owner(record, user_id, org_id)

        llm = llm_service
        conversation_snippet = "\n".join(
            [f"{m.get('role', 'user')}: {m.get('message', '')}" for m in record.chat_history[-8:]]
        )
        prompt = (
            "You are a FinOps IaC assistant helping a client review a template.\n"
            f"File: {record.filename}\n"
            f"Format: {record.format}\n"
            f"Summary: {record.summary}\n"
            f"Pros: {record.pros}\n"
            f"Cons: {record.cons}\n"
            f"Cost Analysis: {json.dumps(record.cost_analysis)}\n"
            f"Suggested Improvements: {record.improvements}\n"
            f"Conversation so far:\n{conversation_snippet}\n\n"
            f"User question: {question}\n"
            "Answer clearly in <= 8 bullet points with actionable guidance."
        )

        answer = await llm.call_llm(prompt=prompt, max_tokens=900)
        if not answer or "unable" in answer.lower() and len(answer) < 120:
            top_cost = sorted(
                record.cost_analysis,
                key=lambda r: float(r.get("estimated_monthly_cost_usd", 0.0)),
                reverse=True,
            )[:3]
            lines = [
                "Here is a practical answer based on the uploaded IaC analysis:",
                f"- Main risk themes: {', '.join(record.cons[:3])}",
                f"- Best immediate actions: {', '.join(record.improvements[:3])}",
            ]
            for item in top_cost:
                lines.append(
                    f"- Estimated savings: {item['service']} / {item['config']} -> ${item['estimated_monthly_cost_usd']:.2f}/month"
                )
            answer = "\n".join(lines)

        record.chat_history.append({"role": "user", "message": question})
        record.chat_history.append({"role": "assistant", "message": answer})
        return answer

    async def generate_final_version(
        self,
        analysis_id: str,
        goals: Optional[str] = None,
        user_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> IacAnalysisRecord:
        record = self.get_record(analysis_id)
        if not record:
            raise ValueError("Analysis session not found")

        self._assert_owner(record, user_id, org_id)

        llm = llm_service
        prompt = (
            "Generate an improved IaC file while preserving semantic intent.\n"
            f"Filename: {record.filename}\n"
            f"Format: {record.format}\n"
            f"Known improvements: {record.improvements}\n"
            f"Additional goals: {goals or 'None'}\n"
            f"Original file:\n{record.original_content}\n\n"
            "Return only the improved file content. Keep syntax valid."
        )

        generated = await llm.call_llm(prompt=prompt, max_tokens=2200)
        if not generated or len(generated.strip()) < 40:
            generated = self._apply_basic_improvements(record.original_content, record.format, record.improvements)

        # Strip markdown fencing if the model wrapped content.
        generated = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", generated.strip())
        generated = re.sub(r"\n```$", "", generated)

        if len(generated.strip()) < 40:
            generated = self._apply_basic_improvements(record.original_content, record.format, record.improvements)

        record.improved_content = generated
        return record


iac_analysis_service = IacAnalysisService()
