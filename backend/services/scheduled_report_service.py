"""
Scheduled Report Service - Handles creation, execution, and delivery of scheduled reports
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import structlog
from croniter import croniter
import asyncio
from jinja2 import Template
import pandas as pd
from io import BytesIO

from backend.services.database import DatabaseService
from backend.agents.multi_agent_workflow import execute_multi_agent_query
from backend.services.email_service import EmailService
from backend.services.s3_service import S3Service

logger = structlog.get_logger(__name__)


class ScheduledReportService:
    """Service for managing scheduled reports"""
    
    def __init__(self):
        self.db = DatabaseService()
        self.email_service = EmailService()
        self.s3_service = S3Service()
    
    async def create_scheduled_report(
        self,
        name: str,
        report_type: str,
        query_params: Dict[str, Any],
        frequency: str,
        format: str,
        delivery_methods: List[str],
        recipients: Dict[str, List[str]],
        created_by: str,
        cron_expression: Optional[str] = None,
        timezone: str = "UTC",
        description: Optional[str] = None,
        report_template: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new scheduled report"""
        
        # Calculate next run time
        next_run = self._calculate_next_run(frequency, cron_expression, timezone)
        
        query = """
            INSERT INTO scheduled_reports (
                name, description, created_by, report_type, report_template,
                query_params, frequency, cron_expression, timezone, next_run_at,
                format, delivery_methods, recipients
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
            )
            RETURNING id, name, next_run_at
        """
        
        result = await self.db.execute(
            query,
            name, description, created_by, report_type, report_template,
            query_params, frequency, cron_expression, timezone, next_run,
            format, delivery_methods, recipients
        )
        
        logger.info(
            "scheduled_report_created",
            report_id=result['id'],
            name=name,
            next_run=next_run
        )
        
        return result
    
    async def execute_due_reports(self):
        """Execute all reports that are due to run"""
        
        query = """
            SELECT id, name, report_type, query_params, format, delivery_methods, recipients, report_template
            FROM scheduled_reports
            WHERE is_active = true
            AND next_run_at <= NOW()
            ORDER BY next_run_at ASC
        """
        
        reports = await self.db.fetch_all(query)
        
        logger.info("executing_scheduled_reports", count=len(reports))
        
        for report in reports:
            try:
                await self._execute_report(report)
            except Exception as e:
                logger.error(
                    "report_execution_failed",
                    report_id=report['id'],
                    error=str(e)
                )
    
    async def _execute_report(self, report: Dict[str, Any]):
        """Execute a single report"""
        
        execution_id = await self._create_execution_record(report['id'])
        start_time = datetime.utcnow()
        
        try:
            # Execute query using multi-agent workflow
            query_start = datetime.utcnow()
            
            result = await execute_multi_agent_query(
                query=self._build_query_from_params(report['query_params']),
                conversation_id=f"scheduled_report_{report['id']}",
                chat_history=[],
                previous_context={}
            )
            
            query_duration = (datetime.utcnow() - query_start).total_seconds() * 1000
            
            # Generate report file
            gen_start = datetime.utcnow()
            file_path, file_size = await self._generate_report_file(
                report, result, execution_id
            )
            gen_duration = (datetime.utcnow() - gen_start).total_seconds() * 1000
            
            # Deliver report
            delivery_status = await self._deliver_report(
                report, file_path, result
            )
            
            # Update execution record
            total_duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            await self._complete_execution(
                execution_id=execution_id,
                status='completed',
                data_results=result.get('data', {}),
                file_path=file_path,
                file_size=file_size,
                delivery_status=delivery_status,
                query_duration_ms=int(query_duration),
                generation_duration_ms=int(gen_duration),
                total_duration_ms=int(total_duration)
            )
            
            # Update next run time
            await self._update_next_run(report)
            
            logger.info(
                "report_executed_successfully",
                report_id=report['id'],
                execution_id=execution_id,
                duration_ms=total_duration
            )
            
        except Exception as e:
            await self._complete_execution(
                execution_id=execution_id,
                status='failed',
                error_message=str(e)
            )
            raise
    
    async def _create_execution_record(self, report_id: str) -> str:
        """Create execution record"""
        query = """
            INSERT INTO report_executions (scheduled_report_id, status)
            VALUES ($1, 'running')
            RETURNING id
        """
        result = await self.db.execute(query, report_id)
        return result['id']
    
    async def _complete_execution(
        self,
        execution_id: str,
        status: str,
        data_results: Optional[Dict] = None,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        delivery_status: Optional[Dict] = None,
        query_duration_ms: Optional[int] = None,
        generation_duration_ms: Optional[int] = None,
        total_duration_ms: Optional[int] = None,
        error_message: Optional[str] = None
    ):
        """Complete execution record"""
        query = """
            UPDATE report_executions
            SET status = $1,
                completed_at = NOW(),
                data_results = $2,
                report_file_path = $3,
                file_size_bytes = $4,
                delivery_status = $5,
                query_duration_ms = $6,
                generation_duration_ms = $7,
                total_duration_ms = $8,
                error_message = $9
            WHERE id = $10
        """
        await self.db.execute(
            query, status, data_results, file_path, file_size,
            delivery_status, query_duration_ms, generation_duration_ms,
            total_duration_ms, error_message, execution_id
        )
    
    def _build_query_from_params(self, params: Dict[str, Any]) -> str:
        """Build natural language query from structured parameters"""
        # Convert structured params to conversational query
        query_parts = []
        
        if params.get('services'):
            query_parts.append(f"for {', '.join(params['services'])}")
        
        if params.get('time_range'):
            query_parts.append(f"from {params['time_range']['start']} to {params['time_range']['end']}")
        
        if params.get('dimensions'):
            query_parts.append(f"broken down by {', '.join(params['dimensions'])}")
        
        return f"Show cost breakdown {' '.join(query_parts)}"
    
    async def _generate_report_file(
        self,
        report: Dict[str, Any],
        result: Dict[str, Any],
        execution_id: str
    ) -> tuple[str, int]:
        """Generate report file in specified format"""
        
        if report['format'] == 'CSV':
            return await self._generate_csv(result, execution_id)
        elif report['format'] == 'PDF':
            return await self._generate_pdf(report, result, execution_id)
        elif report['format'] == 'EXCEL':
            return await self._generate_excel(result, execution_id)
        elif report['format'] == 'JSON':
            return await self._generate_json(result, execution_id)
        elif report['format'] == 'HTML':
            return await self._generate_html(report, result, execution_id)
        else:
            raise ValueError(f"Unsupported format: {report['format']}")
    
    async def _generate_csv(self, result: Dict, execution_id: str) -> tuple[str, int]:
        """Generate CSV report"""
        data = result.get('data', {}).get('cost_data', [])
        df = pd.DataFrame(data)
        
        buffer = BytesIO()
        df.to_csv(buffer, index=False)
        content = buffer.getvalue()
        
        file_path = f"reports/{execution_id}.csv"
        await self.s3_service.upload(file_path, content)
        
        return file_path, len(content)
    
    async def _generate_html(self, report: Dict, result: Dict, execution_id: str) -> tuple[str, int]:
        """Generate HTML report using template"""
        template_str = report.get('report_template') or self._get_default_template()
        template = Template(template_str)
        
        html_content = template.render(
            report_name=report['name'],
            generated_at=datetime.utcnow(),
            data=result.get('data', {}),
            charts=result.get('charts', []),
            message=result.get('message', '')
        )
        
        file_path = f"reports/{execution_id}.html"
        await self.s3_service.upload(file_path, html_content.encode())
        
        return file_path, len(html_content)
    
    async def _deliver_report(
        self,
        report: Dict[str, Any],
        file_path: str,
        result: Dict[str, Any]
    ) -> Dict[str, str]:
        """Deliver report via configured methods"""
        
        delivery_status = {}
        recipients = report['recipients']
        
        for method in report['delivery_methods']:
            try:
                if method == 'EMAIL':
                    await self._deliver_via_email(
                        recipients.get('emails', []),
                        report,
                        file_path,
                        result
                    )
                    delivery_status['email'] = 'sent'
                    
                elif method == 'WEBHOOK':
                    await self._deliver_via_webhook(
                        recipients.get('webhooks', []),
                        result
                    )
                    delivery_status['webhook'] = 'sent'
                    
                elif method == 'S3':
                    # Already uploaded to S3
                    delivery_status['s3'] = 'uploaded'
                    
                elif method == 'SLACK':
                    await self._deliver_via_slack(
                        recipients.get('slack_channels', []),
                        report,
                        file_path,
                        result
                    )
                    delivery_status['slack'] = 'sent'
                    
            except Exception as e:
                logger.error(f"{method.lower()}_delivery_failed", error=str(e))
                delivery_status[method.lower()] = f'failed: {str(e)}'
        
        return delivery_status
    
    async def _deliver_via_email(
        self,
        emails: List[str],
        report: Dict,
        file_path: str,
        result: Dict
    ):
        """Send report via email"""
        subject = f"Scheduled Report: {report['name']}"
        body = f"""
        Your scheduled report "{report['name']}" has been generated.
        
        Report Summary:
        {result.get('message', 'No summary available')}
        
        Please find the detailed report attached.
        """
        
        await self.email_service.send(
            to=emails,
            subject=subject,
            body=body,
            attachments=[file_path]
        )
    
    async def _deliver_via_webhook(self, webhooks: List[str], result: Dict):
        """Deliver report data to webhooks"""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            for webhook_url in webhooks:
                await session.post(webhook_url, json=result)
    
    async def _deliver_via_slack(
        self,
        channels: List[str],
        report: Dict,
        file_path: str,
        result: Dict
    ):
        """Post report to Slack channels"""
        # Implementation would use Slack API
        pass
    
    def _calculate_next_run(
        self,
        frequency: str,
        cron_expression: Optional[str],
        timezone: str
    ) -> datetime:
        """Calculate next run time based on frequency"""
        
        if frequency == 'CUSTOM_CRON' and cron_expression:
            cron = croniter(cron_expression, datetime.utcnow())
            return cron.get_next(datetime)
        
        now = datetime.utcnow()
        
        if frequency == 'DAILY':
            return now + timedelta(days=1)
        elif frequency == 'WEEKLY':
            return now + timedelta(weeks=1)
        elif frequency == 'MONTHLY':
            return now + timedelta(days=30)  # Approximate
        elif frequency == 'QUARTERLY':
            return now + timedelta(days=90)  # Approximate
        
        return now + timedelta(days=1)  # Default to daily
    
    async def _update_next_run(self, report: Dict[str, Any]):
        """Update next run time for report"""
        next_run = self._calculate_next_run(
            report['frequency'],
            report.get('cron_expression'),
            report.get('timezone', 'UTC')
        )
        
        query = """
            UPDATE scheduled_reports
            SET last_run_at = NOW(),
                next_run_at = $1
            WHERE id = $2
        """
        await self.db.execute(query, next_run, report['id'])
    
    def _get_default_template(self) -> str:
        """Get default HTML template"""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>{{ report_name }}</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                .summary { background: #f5f5f5; padding: 20px; margin: 20px 0; }
                table { border-collapse: collapse; width: 100%; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #4CAF50; color: white; }
            </style>
        </head>
        <body>
            <h1>{{ report_name }}</h1>
            <p>Generated at: {{ generated_at }}</p>
            <div class="summary">{{ message }}</div>
            <!-- Chart and data sections would go here -->
        </body>
        </html>
        """


# Scheduler instance (would be run as background task)
scheduled_report_service = ScheduledReportService()
