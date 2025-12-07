import React, { useState, useRef, useEffect } from 'react';
import type { ChangeEvent } from 'react';
import {
  Box,
  Paper,
  TextField,
  IconButton,
  Typography,
  Avatar,
  Card,
  CardContent,
  Chip,
  Button,
  CircularProgress,
  Alert,
  Fade,
  Grid,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow
} from '@mui/material';
import {
  Send as SendIcon,
  AttachMoney as MoneyIcon,
  Download as DownloadIcon,
  Lightbulb as LightbulbIcon,
  SmartToy as BotIcon,
  Person as PersonIcon,
  Add as AddIcon,
  ExpandMore as ExpandMoreIcon,
  Code as CodeIcon
} from '@mui/icons-material';
import { Line, Bar, Pie, Scatter } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
} from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import MarkdownRenderer from './MarkdownRenderer';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
  ChartDataLabels
);

const SERVICE_LABEL_MAP: Record<string, string> = {
  'amazon elastic compute cloud': 'EC2',
  'amazonelasticcomputecloud': 'EC2',
  'elastic compute cloud': 'EC2',
  ec2: 'EC2',
  'amazon simple storage service': 'S3',
  'amazonsimplestorageservice': 'S3',
  'simple storage service': 'S3',
  'amazon s3': 'S3',
  'amazon relational database service': 'RDS',
  'amazonrelationaldatabaseservice': 'RDS',
  'relational database service': 'RDS',
  'amazon dynamodb': 'DynamoDB',
  'amazondynamodb': 'DynamoDB',
  dynamodb: 'DynamoDB',
  'amazon cloudfront': 'CloudFront',
  'amazoncloudfront': 'CloudFront',
  cloudfront: 'CloudFront',
  'amazon cloudwatch': 'CloudWatch',
  'amazoncloudwatch': 'CloudWatch',
  cloudwatch: 'CloudWatch',
  'amazon virtual private cloud': 'VPC',
  'amazonvirtualprivatecloud': 'VPC',
  'virtual private cloud': 'VPC',
  'elastic load balancing': 'ELB',
  'elasticloadbalancing': 'ELB',
  'application load balancer': 'ALB',
  'network load balancer': 'NLB',
  'aws lambda': 'Lambda',
  'awslambda': 'Lambda',
  lambda: 'Lambda',
  'aws key management service': 'KMS',
  'awskeymanagementservice': 'KMS',
  'key management service': 'KMS',
  'aws security hub': 'Security Hub',
  'awssecurityhub': 'Security Hub',
  'amazon elasticache': 'ElastiCache',
  'amazonelasticache': 'ElastiCache',
  elasticache: 'ElastiCache',
  'amazon redshift': 'Redshift',
  'amazonredshift': 'Redshift',
  'amazon guardduty': 'GuardDuty',
  'amazonguardduty': 'GuardDuty',
  'aws glue': 'Glue',
  'awsglue': 'Glue',
  'aws backup': 'Backup',
  'awsbackup': 'Backup',
  'amazon quicksight': 'QuickSight',
  'amazonquicksight': 'QuickSight',
  'amazon route 53': 'Route 53',
  'amazonroute 53': 'Route 53',
  'amazonroute53': 'Route 53',
  'route 53': 'Route 53',
  'amazon elastic container service': 'ECS',
  'amazonelasticcontainerservice': 'ECS',
  'elastic container service': 'ECS',
  'amazon elastic kubernetes service': 'EKS',
  'amazonelastickubernetesservice': 'EKS',
  'elastic kubernetes service': 'EKS',
  'amazon elastic mapreduce': 'EMR',
  'amazonelasticmapreduce': 'EMR',
  'elastic mapreduce': 'EMR',
  'aws identity and access management': 'IAM',
  'awsidentityandaccessmanagement': 'IAM',
  'identity and access management': 'IAM',
  'amazon simple queue service': 'SQS',
  'amazonsimplequeueservice': 'SQS',
  'simple queue service': 'SQS',
  'amazon simple notification service': 'SNS',
  'amazonsimplenotificationservice': 'SNS',
  'simple notification service': 'SNS',
  'aws cloudtrail': 'CloudTrail',
  'awscloudtrail': 'CloudTrail',
  cloudtrail: 'CloudTrail',
  'aws cloudformation': 'CloudFormation',
  'awscloudformation': 'CloudFormation',
  cloudformation: 'CloudFormation'
};

const normalizeServiceKey = (label: string) =>
  label
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ');

const transformServiceLabel = (label: string): string => {
  const trimmed = label.trim();
  if (!trimmed) {
    return label;
  }

  // Helper: middle-ellipsis for very long labels
  const abbreviateMiddle = (text: string, maxLen = 26, head = 12, tail = 10) => {
    if (text.length <= maxLen) return text;
    return `${text.slice(0, head)}…${text.slice(-tail)}`;
  };

  // If this looks like an ARN or a path-like identifier, extract the meaningful tail
  if (/^arn:/i.test(trimmed) || /[:/]/.test(trimmed)) {
    // Try common AWS resource patterns first (db:, table/, function:, topic:, queue: etc.)
    const specific = trimmed.match(/(?::db:|:cluster:|:instance:|:table:|:function:|:topic:|:queue:|:log-group:|:stream:|:rule:|:alarm:|:distribution:|:repository:|:dataset:|:crawler:|:application:|:stateMachine:|:trail:|:vault:|:backup-vault:|:db-instance:|:db-cluster:)[^:/]*[:/]*([^:/]+)$/i);
    if (specific && specific[1]) {
      return abbreviateMiddle(specific[1]);
    }
    // Otherwise, use the last token after ':' or '/'
    const parts = trimmed.split(/[/:]/).filter(Boolean);
    const tail = parts[parts.length - 1] || trimmed;
    return abbreviateMiddle(tail);
  }

  const normalized = normalizeServiceKey(trimmed);
  if (SERVICE_LABEL_MAP[normalized]) {
    return SERVICE_LABEL_MAP[normalized];
  }

  const spaced = trimmed.replace(/([a-z])([A-Z])/g, '$1 $2');

  // Remove Amazon/AWS prefixes for generic shortening
  const withoutPrefixes = spaced
    .replace(/^(Amazon|AWS)/i, '')
    .replace(/\b(Amazon|AWS)\b/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!withoutPrefixes) {
    return trimmed;
  }

  const normalizedWithout = normalizeServiceKey(withoutPrefixes);
  if (SERVICE_LABEL_MAP[normalizedWithout]) {
    return SERVICE_LABEL_MAP[normalizedWithout];
  }

  if (/elastic compute cloud/i.test(trimmed)) {
    return 'EC2';
  }
  if (/simple storage service/i.test(trimmed)) {
    return 'S3';
  }
  if (/relational database service/i.test(trimmed)) {
    const engineMatch = trimmed.match(/for\s+(.+)$/i);
    return engineMatch ? `RDS (${engineMatch[1].trim()})` : 'RDS';
  }
  if (/elastic container service/i.test(trimmed)) {
    return 'ECS';
  }
  if (/elastic kubernetes service/i.test(trimmed)) {
    return 'EKS';
  }
  if (/elastic mapreduce/i.test(trimmed)) {
    return 'EMR';
  }
  if (/simple queue service/i.test(trimmed)) {
    return 'SQS';
  }
  if (/simple notification service/i.test(trimmed)) {
    return 'SNS';
  }
  if (/key management service/i.test(trimmed)) {
    return 'KMS';
  }
  if (/identity and access management/i.test(trimmed)) {
    return 'IAM';
  }

  // Final safety: abbreviate overly long residual labels
  const finalLabel = withoutPrefixes || trimmed;
  return finalLabel.length > 26 ? finalLabel.slice(0, 24) + '…' : finalLabel;
};

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  charts?: any[];
  insights?: any[];  // Legacy field
  suggestions?: string[];
  actionItems?: any[];
  athenaQuery?: string;  // SQL query executed for cost data
  results?: any[];  // Raw data rows for table rendering
  // Structured response fields
  summary?: string;
  structuredInsights?: Array<{category: string; description: string}>;
  recommendations?: Array<{action: string; description: string}>;
  metadata?: {
    time_period?: string;
    scope?: string;
    filters?: string;
    status?: 'ok' | 'needs_clarification' | 'llm_error' | 'unsupported';
    clarification?: string[];
  };
}

interface ChatInterfaceProps {
  onSendMessage?: (message: string) => void;
  onClearChat?: () => void;
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({ onSendMessage }) => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hello! I\'m your AI-powered FinOps assistant. I can help you analyze AWS costs, identify optimization opportunities, and answer questions about your cloud spending. What would you like to know?',
      timestamp: new Date(),
      suggestions: [
        'Show me my AWS costs for the last 30 days',
        'What are my top 5 most expensive services?',
        'How can I optimize my EC2 costs?',
        'Generate a cost optimization report'
      ]
    }
  ]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationContext, setConversationContext] = useState<Record<string, any>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Auto-focus input on component mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSendMessage = async () => {
    if (!inputMessage.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: inputMessage,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    const messageToSend = inputMessage;
    setInputMessage('');
    setIsLoading(true);

    try {
      // Call real backend API
      // In AWS deployment with ALB, both frontend and backend are behind same ALB
      // ALB routes /api/* to backend service based on path rules
      // So we just use relative path /api/v1/chat and let ALB handle routing
      const endpoint = '/api/v1/chat';
      
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: messageToSend,
          conversation_id: conversationId, // Maintain conversation context
          chat_history: messages.map(msg => ({
            role: msg.role,
            content: msg.content,
            timestamp: msg.timestamp.toISOString()
          })), // Send full conversation history
          include_reasoning: false,
          context: conversationContext // Pass accumulated context
        })
      });

      if (!response.ok) {
        const errorBody = await response.text();
        console.error('API error response:', errorBody);

        let errorDetail = `Request failed with status ${response.status}`;
        if (errorBody) {
          try {
            const parsedError = JSON.parse(errorBody);
            errorDetail = parsedError.detail || parsedError.message || errorDetail;
          } catch {
            errorDetail = `${errorDetail}: ${errorBody}`;
          }
        }

        throw new Error(errorDetail);
      }

      const data = await response.json();
      
      // Store conversation ID from first response
      if (!conversationId && data.conversation_id) {
        setConversationId(data.conversation_id);
      }
      
      // Update conversation context with latest response data
      if (data.context) {
        setConversationContext((prev) => ({
          ...prev,
          ...data.context,
          last_query: messageToSend,
          last_intent: data.user_intent,
          cost_data_fetched: data.charts && data.charts.length > 0
        }));
      }
      
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.message || 'I received your message but have no response.',
        timestamp: new Date(),
        charts: data.charts || [],
        insights: data.insights || [],
        suggestions: data.suggestions || [],
        actionItems: data.action_items || [],
        athenaQuery: data.athena_query || undefined,  // Include SQL query if available
        results: data.results || [],  // Include results data for table rendering
        // Structured response fields
        summary: data.summary || '',
        structuredInsights: data.structuredInsights || [],  // Changed from data.insights
        recommendations: data.recommendations || [],
        metadata: data.metadata || undefined  // Changed from data.context
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Chat API error:', error);

      let friendlyError = 'I apologize, but I encountered an error processing your request. Please ensure the backend is running and try again.';
      if (error instanceof Error && error.message) {
        friendlyError = `I ran into an issue: ${error.message}`;
      }

      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: friendlyError,
        timestamp: new Date(),
        suggestions: [
          'Double-check that the backend service is reachable',
          'Try rephrasing or simplifying your question',
          'Review the server logs for additional details'
        ]
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }

    if (onSendMessage) {
      onSendMessage(messageToSend);
    }
  };

  const handleKeyPress = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSendMessage();
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setInputMessage(suggestion);
    inputRef.current?.focus();
  };

  const handleClearChat = () => {
    setMessages([{
      id: '1',
      role: 'assistant',
      content: 'Hello! I\'m your AI-powered FinOps assistant. I can help you analyze AWS costs, identify optimization opportunities, and answer questions about your cloud spending. What would you like to know?',
      timestamp: new Date(),
      suggestions: [
        'Show me my AWS costs for the last 30 days',
        'What are my top 5 most expensive services?',
        'How can I optimize my EC2 costs?',
        'Generate a cost optimization report'
      ]
    }]);
    setInputMessage('');
    setConversationId(null); // Reset conversation ID
    setConversationContext({}); // Reset conversation context
    // Optionally, you could also reset any other state related to the chat session here
    // Focus input after clearing chat - use requestAnimationFrame to ensure DOM updates
    requestAnimationFrame(() => {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
    });
  };

  const handleExportChart = (chart: any, chartIndex: number, messageId: string) => {
    try {
      // Get the chart canvas element
      const chartId = `chart-${messageId}-${chartIndex}`;
      const canvas = document.getElementById(chartId) as HTMLCanvasElement;
      
      if (!canvas) {
        console.error('Chart canvas not found');
        return;
      }

      // Convert canvas to blob and download
      canvas.toBlob((blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = `${chart.title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}_${Date.now()}.png`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
        }
      });
    } catch (error) {
      console.error('Error exporting chart:', error);
    }
  };

  const renderChart = (chart: any, chartIndex: number, messageId: string) => {
    const chartId = `chart-${messageId}-${chartIndex}`;
    const {
      plugins: configPlugins = {},
      scales: configScales = {},
      indexAxis: configIndexAxis,
      ...restConfig
    } = chart.config || {};

    const { legend: legendConfig = {}, title: titleConfig = {}, ...otherPluginConfig } = configPlugins;
    const resolvedIndexAxis = configIndexAxis ?? restConfig.indexAxis ?? undefined;

      const mergeScales = (
        defaults: Record<string, any>,
        overrides: Record<string, any>
      ) => {
        const mergedKeys = new Set([
          ...Object.keys(defaults),
          ...Object.keys(overrides)
        ]);
        const result: Record<string, any> = {};      mergedKeys.forEach((key) => {
        const defaultAxis = defaults[key] || {};
        const overrideAxis = overrides[key] || {};
        result[key] = {
          ...defaultAxis,
          ...overrideAxis,
          ticks: {
            ...(defaultAxis.ticks || {}),
            ...(overrideAxis.ticks || {})
          },
          grid: {
            ...(defaultAxis.grid || {}),
            ...(overrideAxis.grid || {})
          }
        };
      });

      return result;
    };

    const baseAxisStyles = {
      grid: {
        color: 'rgba(148, 163, 184, 0.2)',
        drawBorder: false,
      },
      ticks: {
        color: '#475467',
        font: {
          size: 11
        }
      }
    };

    const isBarLike = ['bar', 'column', 'stacked_bar', 'clustered_bar'].includes(chart.type);
    const datasetCount = Array.isArray(chart.data?.datasets) ? chart.data.datasets.length : 0;
    const hasMultipleDatasets = datasetCount > 1;

    const defaultScales = (() => {
      if (isBarLike) {
        if (resolvedIndexAxis === 'y') {
          return {
            x: {
              ...baseAxisStyles,
              beginAtZero: true,
              ticks: {
                ...baseAxisStyles.ticks,
                callback: (value: number | string) => {
                  const numeric = typeof value === 'number' ? value : Number(value);
                  if (Number.isFinite(numeric)) {
                    // For large numbers, use toLocaleString without decimals
                    // For smaller numbers with decimals, show 2 decimal places
                    return numeric >= 1000 
                      ? '$' + Math.round(numeric).toLocaleString()
                      : '$' + numeric.toFixed(2);
                  }
                  return value;
                }
              },
              grid: {
                ...baseAxisStyles.grid,
                borderDash: [4, 4]
              }
            },
            y: {
              ...baseAxisStyles,
              ticks: {
                ...baseAxisStyles.ticks,
                padding: 6
              },
              grid: {
                ...baseAxisStyles.grid,
                display: false
              }
            }
          };
        }
        return {
          x: {
            ...baseAxisStyles,
            ticks: {
              ...baseAxisStyles.ticks,
              maxRotation: 45,
              minRotation: 30,
              padding: 6,
              callback: function(value: any, index: number, ticks: any[]) {
                const scale: any = this;
                const tickLabel = ticks?.[index]?.label;
                const scaleLabel = typeof scale?.getLabelForValue === 'function'
                  ? scale.getLabelForValue(value)
                  : undefined;
                const dataLabel = Array.isArray(scale?.chart?.data?.labels)
                  ? scale.chart.data.labels[index]
                  : undefined;
                const rawLabel = tickLabel ?? scaleLabel ?? dataLabel ?? value;
                if (typeof rawLabel === 'string' && /^\d{4}-\d{2}/.test(rawLabel)) {
                  try {
                    const date = new Date(rawLabel);
                    return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
                  } catch {
                    return rawLabel;
                  }
                }
                return transformAxisLabel(rawLabel);
              }
            }
          },
          y: {
            ...baseAxisStyles,
            beginAtZero: true,
            ticks: {
              ...baseAxisStyles.ticks,
              callback: (value: number | string) => {
                const numeric = typeof value === 'number' ? value : Number(value);
                if (Number.isFinite(numeric)) {
                  return numeric >= 1000 
                    ? '$' + Math.round(numeric).toLocaleString()
                    : '$' + numeric.toFixed(2);
                }
                return value;
              }
            }
          }
        };
      }
      return {};
    })();

    const baseLegend = {
      position: 'bottom' as const,
      align: 'start' as const,
      labels: {
        boxWidth: 12,
        boxHeight: 10,
        font: {
          size: 11
        },
        color: '#475467'
      },
      padding: 12
    };

    const legendOptions = {
      ...baseLegend,
      ...legendConfig,
      labels: {
        ...baseLegend.labels,
        ...(legendConfig.labels || {}),
        // For bar/column charts showing services, generate legend from data labels not datasets
        generateLabels: (chartInstance: any) => {
          const hasMultipleDatasets = chartInstance.data.datasets && chartInstance.data.datasets.length > 1;
          
          // If it's a bar chart with single dataset, use labels as legend items
          if (isBarLike && !hasMultipleDatasets && chartInstance.data.labels) {
            return chartInstance.data.labels.map((label: string, i: number) => {
              const dataset = chartInstance.data.datasets[0];
              const backgroundColor = Array.isArray(dataset?.backgroundColor) 
                ? dataset.backgroundColor[i] 
                : dataset?.backgroundColor || '#667eea';
              
              return {
                text: label,
                fillStyle: backgroundColor,
                hidden: false,
                index: i
              };
            });
          }
          
          // Otherwise use default legend generation (for multi-dataset charts)
          return chartInstance.data.datasets.map((dataset: any, i: number) => ({
            text: dataset.label || `Dataset ${i + 1}`,
            fillStyle: dataset.backgroundColor,
            strokeStyle: dataset.borderColor,
            lineWidth: dataset.borderWidth,
            hidden: !chartInstance.isDatasetVisible(i),
            index: i,
            datasetIndex: i
          }));
        }
      }
    };

    const chartOptions = {
      responsive: true,
      maintainAspectRatio: false,
      ...restConfig,
      indexAxis: resolvedIndexAxis,
      layout: {
        padding: {
          top: 40,      // Add top padding to prevent label cutoff
          bottom: 10,
          left: 10,
          right: 10
        }
      },
      plugins: {
        ...otherPluginConfig,
        legend: legendOptions,
        title: {
          display: false, // Disable Chart.js title since we show it in the header
          text: titleConfig.text ?? chart.title,
          ...titleConfig,
        },
        tooltip: {
          callbacks: {
            label: function(context: any) {
              let label = context.dataset.label || '';
              if (label) {
                label += ': ';
              }
              if (context.parsed.y !== null) {
                label += '$' + context.parsed.y.toFixed(2);
              } else if (context.parsed.x !== null) {
                label += '$' + context.parsed.x.toFixed(2);
              } else if (context.parsed !== null) {
                label += '$' + context.parsed.toFixed(2);
              }
              return label;
            }
          }
        },
        datalabels: {
          display: (context: any) => {
            const dataCount = context.chart.data.labels?.length || 0;
            return dataCount <= 10;
          },
          anchor: (context: any) => {
            if (resolvedIndexAxis === 'y') {
              return 'end';
            }
            if (!isBarLike) {
              return context.dataset.data[context.dataIndex] >= 0 ? 'end' : 'start';
            }
            if (hasMultipleDatasets) {
              return context.datasetIndex === 0 ? 'end' : 'start';
            }
            return context.dataset.data[context.dataIndex] >= 0 ? 'end' : 'start';
          },
          align: (context: any) => {
            if (resolvedIndexAxis === 'y') {
              return 'right';
            }
            if (hasMultipleDatasets && isBarLike) {
              return context.datasetIndex === 0 ? 'top' : 'bottom';
            }
            return context.dataset.data[context.dataIndex] >= 0 ? 'top' : 'bottom';
          },
          offset: (context: any) => {
            if (hasMultipleDatasets && resolvedIndexAxis !== 'y') {
              return context.datasetIndex === 0 ? 6 : 6;
            }
            return 4;
          },
          formatter: (value: any) => {
            const numeric = typeof value === 'number' ? value : (typeof value === 'string' ? Number(value.replace(/[^0-9.-]+/g, '')) || 0 : Number(value) || 0);
            // Show label if value is greater than or equal to 0 (including very small positive values)
            return numeric >= 0 ? `$${numeric.toFixed(2)}` : '';
          },
          color: '#475467',
          font: {
            size: 10,
            weight: '600'
          },
          clip: false  // Allow labels to render outside chart area
        },
      },
      scales: {
        ...mergeScales(defaultScales, configScales),
        // CRITICAL: Disable stacking for bar charts showing individual services
        // Backend sends "stacked_bar" but we want individual bars, not stacked
        ...(isBarLike && {
          x: {
            ...mergeScales(defaultScales, configScales).x,
            stacked: false
          },
          y: {
            ...mergeScales(defaultScales, configScales).y,
            stacked: false
          }
        })
      }
    };

    // Robustly extract a human-friendly label from any value (string/object/number)
    const extractLabelText = (value: any): string => {
      if (value == null) return '';
      if (typeof value === 'string') return value;
      if (typeof value === 'number') return String(value);
      if (typeof value === 'object') {
        // Common keys we may receive from back end aggregations
        const candidate = (value as any).label
          ?? (value as any).name
          ?? (value as any).service
          ?? (value as any).key
          ?? (value as any).id;
        return typeof candidate === 'string' ? candidate : JSON.stringify(value);
      }
      return String(value);
    };

    const transformAxisLabel = (value: any) =>
      transformServiceLabel(extractLabelText(value));

    /**
     * Unified Chart Data Normalizer
     * Handles all chart data normalization in one place:
     * - Converts string values to numbers
     * - Rounds values to 2 decimal places
     * - Reduces to top 5 + Others for bar charts with >5 items
     * - Maintains color arrays in sync with data
     * - Transforms service labels
     */
    const normalizeChartData = (data: any) => {
      if (!data || !Array.isArray(data.datasets) || !Array.isArray(data.labels)) {
        return data;
      }

      console.log('🔍 NORMALIZE INPUT:', {
        chartType: chart.type,
        isBarLike,
        labelCount: data.labels.length,
        datasetCount: data.datasets.length,
        firstDataset: data.datasets[0] ? {
          label: data.datasets[0].label,
          dataCount: data.datasets[0].data?.length,
          bgColorType: Array.isArray(data.datasets[0].backgroundColor) ? 'array' : 'single',
          bgColorCount: Array.isArray(data.datasets[0].backgroundColor) ? data.datasets[0].backgroundColor.length : 1,
          sampleData: data.datasets[0].data?.slice(0, 3),
          sampleColors: Array.isArray(data.datasets[0].backgroundColor) ? data.datasets[0].backgroundColor.slice(0, 3) : data.datasets[0].backgroundColor
        } : null
      });

      const maxItemsBeforeGrouping = 5;
      const hasExistingOthersBucket = data.labels.some((label: any) => {
        const text = typeof label === 'string' ? label.trim().toLowerCase() : '';
        return text.startsWith('others');
      });
      const shouldGroupOthers = isBarLike && data.labels.length > maxItemsBeforeGrouping && !hasExistingOthersBucket;

      // Helper: Convert any value to number with 2 decimal places
      const toNumeric = (value: any): number => {
        const num = typeof value === 'string' 
          ? Number(value.replace(/[^0-9.-]+/g, '')) || 0 
          : Number(value) || 0;
        return Math.round(num * 100) / 100;
      };

      // If we need to group into top 5 + Others, calculate sorting ONCE
      let sortedItems: any[] | null = null;
      if (shouldGroupOthers && data.datasets[0]?.data) {
        const numericData = data.datasets[0].data.map(toNumeric);
        sortedItems = data.labels.map((label: any, index: number) => ({
          label,
          index,
          value: numericData[index]
        })).sort((a: any, b: any) => b.value - a.value);
      }

      // Process datasets
      const normalizedDatasets = data.datasets.map((dataset: any) => {
        if (!Array.isArray(dataset.data)) return dataset;

        const numericData = dataset.data.map(toNumeric);

        // If we need to group into top 5 + Others
        if (shouldGroupOthers && sortedItems) {
          const top5 = sortedItems.slice(0, maxItemsBeforeGrouping);
          const others = sortedItems.slice(maxItemsBeforeGrouping);
          const othersSum = toNumeric(others.reduce((sum: number, item: any) => sum + item.value, 0));

          // Get colors for top 5 + default color for Others
          const getColorArray = (colorProp: any, defaultColor: string) => {
            if (!Array.isArray(colorProp)) return colorProp;
            return top5.map((item: any) => colorProp[item.index])
              .concat([defaultColor]);
          };

          return {
            ...dataset,
            data: top5.map((item: any) => item.value).concat([othersSum]),
            backgroundColor: getColorArray(dataset.backgroundColor, 'rgba(158, 158, 158, 0.8)'),
            borderColor: getColorArray(dataset.borderColor, 'rgba(158, 158, 158, 1.0)'),
            label: typeof dataset.label === 'string' ? transformServiceLabel(dataset.label) : dataset.label
          };
        }

        // No grouping needed, just normalize
        return {
          ...dataset,
          data: numericData,
          label: typeof dataset.label === 'string' ? transformServiceLabel(dataset.label) : dataset.label
        };
      });

      // Handle labels
      let normalizedLabels = data.labels;
      if (shouldGroupOthers && sortedItems) {
        normalizedLabels = sortedItems.slice(0, maxItemsBeforeGrouping)
          .map((item: any) => item.label)
          .concat(['Others'])
          .map(transformAxisLabel);
      } else {
        // Ensure labels are strings; Chart.js shows numeric indices if objects leak through
        normalizedLabels = data.labels.map((lbl: any) => transformAxisLabel(lbl));
      }

      return {
        labels: normalizedLabels,
        datasets: normalizedDatasets
      };
    };

    const normalizedData = normalizeChartData(chart.data);

    const commonProps = {
      id: chartId,
      data: normalizedData,
      options: chartOptions
    };

    switch (chart.type) {
      case 'line':
      case 'area':
        return <Line {...commonProps} />;
      case 'bar':
      case 'column':
      case 'stacked_bar':
      case 'clustered_bar':
        return <Bar {...commonProps} />;
      case 'pie':
        return <Pie {...commonProps} />;
      case 'scatter':
        return <Scatter {...commonProps} />;
      default:
        return <div>Unsupported chart type</div>;
    }
  };

  return (
    <Box 
      sx={{ 
        height: '100%',
        display: 'flex', 
        flexDirection: 'column',
        bgcolor: '#f8fafc',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      {/* Messages Area - Scrollable */}
      <Box 
        sx={{ 
          flexGrow: 1, 
          overflow: 'auto', 
          px: 2,
          py: 2,
          pb: 3,
          '&::-webkit-scrollbar': {
            width: '8px',
          },
          '&::-webkit-scrollbar-track': {
            background: 'rgba(0,0,0,0.05)',
            borderRadius: '10px',
          },
          '&::-webkit-scrollbar-thumb': {
            background: 'rgba(0,0,0,0.2)',
            borderRadius: '10px',
            '&:hover': {
              background: 'rgba(0,0,0,0.3)',
            },
          },
        }}
      >
        {messages.map((message) => {
          const hasCharts = message.role === 'assistant' && Array.isArray(message.charts) && message.charts.length > 0;
          const charts = (hasCharts ? message.charts : []) as any[];
          const chartCount = charts.length;

          return (
          <Fade in={true} key={message.id} timeout={600}>
            <Box sx={{ mb: 3.5 }}>
              {/* Message Header with Avatar */}
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 1.5,
                  mb: 1,
                  flexDirection: message.role === 'user' ? 'row-reverse' : 'row'
                }}
              >
                <Avatar
                  sx={{
                    width: 36,
                    height: 36,
                    bgcolor: message.role === 'user' ? '#667eea' : '#f3f4f6',
                    color: message.role === 'user' ? 'white' : '#667eea',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                  }}
                >
                  {message.role === 'user' ? (
                    <PersonIcon sx={{ fontSize: 20 }} />
                  ) : (
                    <BotIcon sx={{ fontSize: 20 }} />
                  )}
                </Avatar>

                {/* Message Bubble or Two-Column Layout */}
                {hasCharts ? (
                  <Box
                    sx={{
                      maxWidth: '90%',
                      width: '100%',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 0.75
                    }}
                  >
                    <Paper
                      elevation={0}
                      sx={{
                        p: { xs: 2, sm: 2.5 },
                        bgcolor: '#ffffff',
                        color: 'text.primary',
                        borderRadius: '18px 18px 18px 4px',
                        boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
                        border: '1px solid rgba(0,0,0,0.06)',
                        transition: 'all 0.2s ease-in-out',
                        overflow: 'hidden',
                        '&:hover': {
                          boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
                        },
                        height: '100%',
                        display: 'flex',
                        flexDirection: 'column'
                      }}
                    >
                      <Grid container spacing={2.5} alignItems="stretch" sx={{ flexGrow: 1 }}>
                        <Grid
                          item
                          xs={12}
                          md={5}
                          sx={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 1.5,
                            justifyContent: chartCount === 1 ? 'center' : 'flex-start',
                            height: '100%'
                          }}
                        >
                          {/* Results heading above charts */}
                          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <Typography 
                              variant="h6" 
                              sx={{ 
                                fontWeight: 600,
                                fontSize: '0.95rem',
                                color: 'text.primary'
                              }}
                            >
                              Results
                            </Typography>
                            {/* Optional export all could go here later */}
                          </Box>
                          {charts.map((chart: any, index: number) => (
                            <Box
                              key={index}
                              sx={{
                                borderRadius: 2,
                                border: '1px solid rgba(0,0,0,0.08)',
                                bgcolor: 'rgba(102, 126, 234, 0.04)',
                                p: 1.75,
                                boxShadow: '0 1px 6px rgba(0,0,0,0.05)',
                                transition: 'all 0.3s ease-in-out',
                                display: 'block',
                                width: '100%',
                                minHeight: chartCount === 1 ? { xs: 250, md: 320 } : 250,
                                '&:hover': {
                                  boxShadow: '0 4px 14px rgba(0,0,0,0.1)',
                                  transform: 'translateY(-2px)'
                                }
                              }}
                            >
                              <Box
                                sx={{
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  alignItems: 'center',
                                  mb: 1.5
                                }}
                              >
                                <Typography 
                                  variant="h6" 
                                  sx={{ 
                                    fontWeight: 600,
                                    fontSize: '0.95rem',
                                    color: 'text.primary'
                                  }}
                                >
                                  {chart.title}
                                </Typography>
                                <Button 
                                  size="small" 
                                  startIcon={<DownloadIcon />}
                                  onClick={() => handleExportChart(chart, index, message.id)}
                                  sx={{
                                    textTransform: 'none',
                                    fontWeight: 500,
                                    fontSize: '0.8rem',
                                    color: '#667eea',
                                    '&:hover': {
                                      bgcolor: 'rgba(102, 126, 234, 0.12)'
                                    }
                                  }}
                                >
                                  Export
                                </Button>
                              </Box>
                              <Box
                                sx={{
                                  position: 'relative',
                                  flexGrow: 1,
                                  minHeight: chartCount === 1 ? { xs: 250, md: 300 } : 280
                                }}
                              >
                                {renderChart(chart, index, message.id)}
                              </Box>
                            </Box>
                          ))}
                        </Grid>
                        <Grid
                          item
                          xs={12}
                          md={7}
                          sx={{
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'flex-start',
                            alignItems: 'flex-start',
                            height: '100%',
                            gap: 1.2 // reduce vertical gap
                          }}
                        >
                          {/* Clarification / Error Guardrail */}
                          {message.metadata && message.metadata.status && message.metadata.status !== 'ok' ? (
                            <Box sx={{ width: '100%' }}>
                              {message.metadata.status === 'needs_clarification' && (
                                <Box sx={{ p: 2, borderRadius: 2, border: '1px dashed rgba(102,126,234,0.4)', bgcolor: 'rgba(102,126,234,0.06)', mb: 2 }}>
                                  <Typography sx={{ fontWeight: 600, mb: 1, color: 'text.primary' }}>I need a quick clarification:</Typography>
                                  <Typography variant="body2" sx={{ color: 'text.secondary', mb: 1 }}>
                                    {Array.isArray(message.metadata.clarification) && message.metadata.clarification.length > 0
                                      ? message.metadata.clarification[0]
                                      : 'Please provide a time period or breakdown preference.'}
                                  </Typography>
                                </Box>
                              )}
                              {message.metadata.status === 'llm_error' && (
                                <Box sx={{ p: 2, borderRadius: 2, border: '1px solid rgba(244,67,54,0.2)', bgcolor: 'rgba(244,67,54,0.06)', mb: 2 }}>
                                  <Typography sx={{ fontWeight: 600, mb: 0.5, color: 'text.primary' }}>I couldn’t process that request reliably.</Typography>
                                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>Try rephrasing or specify a time period (e.g., “November 2025”).</Typography>
                                </Box>
                              )}
                            </Box>
                          ) : null}

                          {/* Structured Response Rendering */}
                          {message.summary || message.structuredInsights || message.recommendations ? (
                            <Box sx={{ width: '100%' }}>
                              {/* 1. Summary Section */}
                              {message.summary && (
                                <Box sx={{ mb: 2 }}>
                                  <Typography 
                                    variant="body1" 
                                    sx={{ 
                                      fontSize: '0.95rem',
                                      lineHeight: 1.6,
                                      color: 'text.primary',
                                      fontWeight: 500
                                    }}
                                  >
                                    <strong>Summary:</strong> {message.summary}
                                  </Typography>
                                </Box>
                              )}

                              {/* 2. Insights Section */}
                              {message.structuredInsights && message.structuredInsights.length > 0 && (
                                <Box sx={{ mb: 2 }}>
                                  <Typography 
                                    variant="h6" 
                                    sx={{ 
                                      fontWeight: 600,
                                      fontSize: '0.95rem',
                                      color: 'text.primary',
                                      mb: 1
                                    }}
                                  >
                                    Insights:
                                  </Typography>
                                  <Box component="ul" sx={{ pl: 3, mb: 0, mt: 0.5 }}>
                                    {message.structuredInsights.map((insight: any, idx: number) => (
                                      <Box 
                                        key={idx}
                                        component="li" 
                                        sx={{ 
                                          fontSize: '0.95rem',
                                          mb: 1,
                                          color: 'text.primary',
                                          lineHeight: 1.6
                                        }}
                                      >
                                        <strong>{insight.category}:</strong> {insight.description}
                                      </Box>
                                    ))}
                                  </Box>
                                </Box>
                              )}
                            </Box>
                          ) : (
                            <Box sx={{ width: '100%' }}>
                              <MarkdownRenderer content={message.content} />
                            </Box>
                          )}
                          
                          {/* Results Data Table */}
                          {message.results && message.results.length > 0 && (
                            <Box sx={{ width: '100%', mt: 0.5 }}>
                              <Typography 
                                variant="h6" 
                                sx={{ 
                                  fontWeight: 600,
                                  fontSize: '0.95rem',
                                  color: 'text.primary',
                                  mb: 1
                                }}
                              >
                                Data Table
                              </Typography>
                              <TableContainer 
                                component={Paper} 
                                sx={{ 
                                  borderRadius: 2,
                                  border: '1px solid rgba(0,0,0,0.08)',
                                  boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
                                  maxHeight: 400,
                                  overflow: 'auto'
                                }}
                              >
                                <Table stickyHeader size="small" sx={{ minWidth: 300 }}>
                                  <TableHead>
                                    <TableRow>
                                      {Object.keys(message.results[0] || {}).map((key) => (
                                        <TableCell 
                                          key={key}
                                          sx={{ 
                                            fontWeight: 600,
                                            bgcolor: 'rgba(102, 126, 234, 0.08)',
                                            color: '#667eea',
                                            textTransform: 'capitalize',
                                            fontSize: '0.85rem'
                                          }}
                                        >
                                          {key.replace(/_/g, ' ')}
                                        </TableCell>
                                      ))}
                                    </TableRow>
                                  </TableHead>
                                  <TableBody>
                                    {message.results.map((row: any, index: number) => (
                                      <TableRow 
                                        key={index}
                                        sx={{ 
                                          '&:nth-of-type(odd)': { bgcolor: 'rgba(0,0,0,0.02)' },
                                          '&:hover': { bgcolor: 'rgba(102, 126, 234, 0.04)' }
                                        }}
                                      >
                                        {Object.entries(row).map(([key, value]: [string, any], cellIndex: number) => (
                                          <TableCell 
                                            key={cellIndex}
                                            sx={{ fontSize: '0.85rem' }}
                                          >
                                            {key.toLowerCase().includes('cost') || key.toLowerCase().includes('usd') 
                                              ? `$${typeof value === 'number' ? value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : value}`
                                              : value}
                                          </TableCell>
                                        ))}
                                      </TableRow>
                                    ))}
                                  </TableBody>
                                </Table>
                              </TableContainer>
                            </Box>
                          )}

                          {/* 4. Scope/Time Period Section */}
                          {message.metadata && (
                            (message.metadata.time_period || message.metadata.scope || message.metadata.filters) && (
                              <Box sx={{ width: '100%', mt: 2, p: 1.5, bgcolor: 'rgba(102, 126, 234, 0.06)', borderRadius: 1, border: '1px solid rgba(102, 126, 234, 0.2)' }}>
                                {message.metadata.time_period && (
                                  <Typography variant="body2" sx={{ fontSize: '0.85rem', color: 'text.secondary', mb: 0.5 }}>
                                    <strong>Period:</strong> {message.metadata.time_period}
                                  </Typography>
                                )}
                                {message.metadata.scope && (
                                  <Typography variant="body2" sx={{ fontSize: '0.85rem', color: 'text.secondary', mb: 0.5 }}>
                                    <strong>Scope:</strong> {message.metadata.scope}
                                  </Typography>
                                )}
                                {message.metadata.filters && (
                                  <Typography variant="body2" sx={{ fontSize: '0.85rem', color: 'text.secondary' }}>
                                    <strong>Filters:</strong> {message.metadata.filters}
                                  </Typography>
                                )}
                              </Box>
                            )
                          )}

                          {/* 5. Recommendations Section */}
                          {message.recommendations && message.recommendations.length > 0 && (
                            <Box sx={{ width: '100%', mt: 2 }}>
                              <Typography 
                                variant="h6" 
                                sx={{ 
                                  fontWeight: 600,
                                  fontSize: '0.95rem',
                                  color: 'text.primary',
                                  mb: 1
                                }}
                              >
                                Recommendations:
                              </Typography>
                              <Box component="ol" sx={{ pl: 3, mb: 0, mt: 0.5 }}>
                                {message.recommendations.map((rec: any, idx: number) => (
                                  <Box 
                                    key={idx}
                                    component="li" 
                                    sx={{ 
                                      fontSize: '0.95rem',
                                      mb: 1,
                                      color: 'text.primary',
                                      lineHeight: 1.6
                                    }}
                                  >
                                    <strong>{rec.action}:</strong> {rec.description}
                                  </Box>
                                ))}
                              </Box>
                            </Box>
                          )}
                        </Grid>
                      </Grid>
                    </Paper>
                    <Typography 
                      variant="caption" 
                      sx={{ 
                        color: 'text.secondary',
                        px: 1,
                        fontSize: '0.75rem',
                        alignSelf: 'flex-start'
                      }}
                    >
                      {message.timestamp.toLocaleTimeString([], { 
                        hour: '2-digit', 
                        minute: '2-digit' 
                      })}
                    </Typography>
                  </Box>
                ) : (
                  <Box
                    sx={{
                      maxWidth: message.role === 'user' ? '75%' : '90%',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 1
                    }}
                  >
                    <Paper
                      elevation={0}
                      sx={{
                        p: 2.5,
                        bgcolor: message.role === 'user' 
                          ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
                          : '#ffffff',
                        background: message.role === 'user' 
                          ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
                          : '#ffffff',
                        color: message.role === 'user' ? 'white' : 'text.primary',
                        borderRadius: message.role === 'user' 
                          ? '18px 18px 4px 18px' 
                          : '18px 18px 18px 4px',
                        boxShadow: message.role === 'user'
                          ? '0 4px 12px rgba(102, 126, 234, 0.25)'
                          : '0 2px 12px rgba(0,0,0,0.08)',
                        border: message.role === 'user' 
                          ? 'none'
                          : '1px solid rgba(0,0,0,0.06)',
                        transition: 'all 0.2s ease-in-out',
                        '&:hover': {
                          boxShadow: message.role === 'user'
                            ? '0 6px 16px rgba(102, 126, 234, 0.3)'
                            : '0 4px 16px rgba(0,0,0,0.12)',
                        }
                      }}
                    >
                      {message.role === 'user' ? (
                        <Typography 
                          variant="body1" 
                          sx={{ 
                            whiteSpace: 'pre-wrap',
                            lineHeight: 1.6,
                            fontSize: '0.95rem'
                          }}
                        >
                          {message.content}
                        </Typography>
                      ) : (
                        <MarkdownRenderer content={message.content} />
                      )}
                    </Paper>
                    {/* Timestamp */}
                    <Typography 
                      variant="caption" 
                      sx={{ 
                        color: 'text.secondary',
                        px: 1,
                        fontSize: '0.75rem',
                        alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start'
                      }}
                    >
                      {message.timestamp.toLocaleTimeString([], { 
                        hour: '2-digit', 
                        minute: '2-digit' 
                      })}
                    </Typography>
                  </Box>
                )}
              </Box>

              {/* Athena SQL Query Display */}
              {message.athenaQuery && message.role === 'assistant' && (
                <Box sx={{ mt: 2, ml: 6, maxWidth: '90%' }}>
                  <Accordion
                    sx={{
                      borderRadius: 2,
                      boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
                      border: '1px solid rgba(0,0,0,0.08)',
                      '&:before': {
                        display: 'none',
                      },
                      overflow: 'hidden'
                    }}
                  >
                    <AccordionSummary
                      expandIcon={<ExpandMoreIcon />}
                      sx={{
                        bgcolor: 'rgba(103, 58, 183, 0.04)',
                        '&:hover': {
                          bgcolor: 'rgba(103, 58, 183, 0.08)',
                        },
                        borderRadius: 2,
                        px: 2.5,
                        py: 1
                      }}
                    >
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                        <CodeIcon sx={{ color: '#673ab7', fontSize: 20 }} />
                        <Typography
                          variant="body2"
                          sx={{
                            fontWeight: 600,
                            color: '#673ab7',
                            fontSize: '0.875rem'
                          }}
                        >
                          View Athena SQL Query
                        </Typography>
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails
                      sx={{
                        p: 0,
                        bgcolor: '#1e1e1e',
                        '& pre': {
                          margin: 0,
                          borderRadius: 0
                        }
                      }}
                    >
                      <SyntaxHighlighter
                        language="sql"
                        style={vscDarkPlus}
                        customStyle={{
                          margin: 0,
                          borderRadius: 0,
                          fontSize: '0.85rem',
                          padding: '16px'
                        }}
                        showLineNumbers
                      >
                        {message.athenaQuery}
                      </SyntaxHighlighter>
                    </AccordionDetails>
                  </Accordion>
                </Box>
              )}

              {/* Insights */}
              {message.insights && message.insights.length > 0 && (
                <Box sx={{ mt: 2, ml: message.role === 'user' ? 0 : 6 }}>
                  <Box 
                    sx={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      gap: 1.5,
                      mb: 1.5
                    }}
                  >
                    <Box
                      sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 32,
                        height: 32,
                        borderRadius: '8px',
                        bgcolor: 'rgba(255, 193, 7, 0.15)',
                      }}
                    >
                      <LightbulbIcon sx={{ color: '#f59e0b', fontSize: 20 }} />
                    </Box>
                    <Typography 
                      variant="h6" 
                      sx={{ 
                        fontWeight: 600,
                        fontSize: '0.95rem',
                        color: 'text.primary'
                      }}
                    >
                      Key Insights
                    </Typography>
                  </Box>
                  <Grid container spacing={1.5}>
                    {message.insights.map((insight: any, index: number) => (
                      <Grid item xs={12} md={6} key={index}>
                        <Alert 
                          severity={insight.type === 'alert' ? 'warning' : insight.type === 'saving' ? 'success' : 'info'}
                          sx={{ 
                            borderRadius: 2.5,
                            boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
                            border: '1px solid',
                            borderColor: insight.type === 'alert' 
                              ? 'rgba(237, 108, 2, 0.2)' 
                              : insight.type === 'saving' 
                                ? 'rgba(46, 125, 50, 0.2)' 
                                : 'rgba(2, 136, 209, 0.2)',
                            '& .MuiAlert-icon': {
                              fontSize: 24
                            }
                          }}
                        >
                          <Typography 
                            variant="subtitle2" 
                            sx={{ 
                              fontWeight: 600,
                              mb: 0.5,
                              fontSize: '0.95rem'
                            }}
                          >
                            {insight.title}
                          </Typography>
                          <Typography 
                            variant="body2"
                            sx={{
                              fontSize: '0.875rem',
                              lineHeight: 1.5
                            }}
                          >
                            {insight.description}
                          </Typography>
                        </Alert>
                      </Grid>
                    ))}
                  </Grid>
                </Box>
              )}

              {/* Action Items */}
              {message.actionItems && message.actionItems.length > 0 && (
                <Box sx={{ mt: 2, ml: message.role === 'user' ? 0 : 6 }}>
                  <Typography 
                    variant="h6" 
                    sx={{ 
                      mb: 1.5,
                      fontWeight: 600,
                      fontSize: '0.95rem',
                      color: 'text.primary'
                    }}
                  >
                    💡 Recommended Actions
                  </Typography>
                  <Grid container spacing={1.5}>
                    {message.actionItems.map((item: any, index: number) => (
                      <Grid item xs={12} key={index}>
                        <Card 
                          elevation={0}
                          sx={{ 
                            borderRadius: 2,
                            border: '2px solid',
                            borderColor: item.priority === 'high' 
                              ? 'rgba(211, 47, 47, 0.3)'
                              : item.priority === 'medium'
                                ? 'rgba(237, 108, 2, 0.3)'
                                : 'rgba(46, 125, 50, 0.3)',
                            bgcolor: 'background.paper',
                            transition: 'all 0.3s ease-in-out',
                            '&:hover': {
                              boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
                              transform: 'translateX(2px)'
                            }
                          }}
                        >
                          <CardContent sx={{ p: 2 }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 2 }}>
                              <Box sx={{ flexGrow: 1 }}>
                                <Typography 
                                  variant="subtitle1" 
                                  sx={{ 
                                    fontWeight: 600, 
                                    mb: 1,
                                    fontSize: '0.95rem',
                                    color: 'text.primary'
                                  }}
                                >
                                  {item.title}
                                </Typography>
                                <Typography 
                                  variant="body2" 
                                  color="text.secondary" 
                                  sx={{ 
                                    mb: 1.5,
                                    lineHeight: 1.5,
                                    fontSize: '0.85rem'
                                  }}
                                >
                                  {item.description}
                                </Typography>
                                <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
                                  <Chip 
                                    label={`${item.priority.charAt(0).toUpperCase() + item.priority.slice(1)} Priority`}
                                    color={item.priority === 'high' ? 'error' : item.priority === 'medium' ? 'warning' : 'success'}
                                    size="small"
                                    sx={{
                                      fontWeight: 600,
                                      fontSize: '0.75rem'
                                    }}
                                  />
                                  {item.estimated_savings && (
                                    <Chip 
                                      icon={<MoneyIcon sx={{ fontSize: 16 }} />}
                                      label={`$${item.estimated_savings.toLocaleString()} savings`}
                                      sx={{
                                        bgcolor: 'rgba(46, 125, 50, 0.15)',
                                        color: '#2e7d32',
                                        fontWeight: 600,
                                        fontSize: '0.75rem',
                                        '& .MuiChip-icon': {
                                          color: '#2e7d32'
                                        }
                                      }}
                                      size="small"
                                    />
                                  )}
                                  <Chip 
                                    label={`${item.effort_level.charAt(0).toUpperCase() + item.effort_level.slice(1)} effort`}
                                    variant="outlined"
                                    size="small"
                                    sx={{
                                      fontWeight: 500,
                                      fontSize: '0.75rem'
                                    }}
                                  />
                                </Box>
                              </Box>
                              <Button 
                                variant="outlined" 
                                size="small"
                                sx={{
                                  textTransform: 'none',
                                  fontWeight: 600,
                                  borderRadius: 2,
                                  minWidth: '100px',
                                  borderColor: '#667eea',
                                  color: '#667eea',
                                  '&:hover': {
                                    bgcolor: 'rgba(102, 126, 234, 0.08)',
                                    borderColor: '#667eea'
                                  }
                                }}
                              >
                                Learn More
                              </Button>
                            </Box>
                          </CardContent>
                        </Card>
                      </Grid>
                    ))}
                  </Grid>
                </Box>
              )}

              {/* Suggestions */}
              {message.suggestions && message.suggestions.length > 0 && (
                <Box sx={{ mt: 2.5, ml: message.role === 'user' ? 0 : 6 }}>
                  <Typography 
                    variant="body2" 
                    sx={{ 
                      mb: 1.5,
                      fontWeight: 500,
                      color: 'text.secondary',
                      fontSize: '0.85rem'
                    }}
                  >
                    💬 Suggested follow-up questions:
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
                    {message.suggestions.map((suggestion: string, index: number) => (
                      <Chip
                        key={index}
                        label={suggestion}
                        onClick={() => handleSuggestionClick(suggestion)}
                        clickable
                        variant="outlined"
                        size="medium"
                        sx={{
                          borderRadius: 2.5,
                          borderColor: 'rgba(102, 126, 234, 0.3)',
                          color: '#667eea',
                          fontWeight: 500,
                          fontSize: '0.85rem',
                          py: 2.5,
                          transition: 'all 0.2s ease-in-out',
                          '&:hover': {
                            bgcolor: 'rgba(102, 126, 234, 0.08)',
                            borderColor: '#667eea',
                            transform: 'translateY(-2px)',
                            boxShadow: '0 4px 12px rgba(102, 126, 234, 0.2)'
                          }
                        }}
                      />
                    ))}
                  </Box>
                </Box>
              )}
            </Box>
          </Fade>
        );
        })}

        {isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'flex-start', mb: 2, px: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
              <Avatar
                sx={{
                  width: 36,
                  height: 36,
                  bgcolor: '#f3f4f6',
                  color: '#667eea',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                }}
              >
                <BotIcon sx={{ fontSize: 20 }} />
              </Avatar>
              <Paper 
                elevation={0} 
                sx={{ 
                  p: 2.5, 
                  bgcolor: '#ffffff',
                  borderRadius: '18px 18px 18px 4px',
                  boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
                  border: '1px solid rgba(0,0,0,0.06)'
                }}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                  <CircularProgress size={20} sx={{ color: '#667eea' }} />
                  <Typography 
                    variant="body2" 
                    sx={{ 
                      color: 'text.secondary',
                      fontWeight: 500
                    }}
                  >
                    Analyzing your request...
                  </Typography>
                </Box>
              </Paper>
            </Box>
          </Box>
        )}

        <div ref={messagesEndRef} />
      </Box>

      {/* Fixed Footer with Input and Buttons */}
      <Paper 
        elevation={3} 
        sx={{ 
          position: 'sticky',
          bottom: 0,
          left: 0,
          right: 0,
          p: 2.5,
          borderRadius: 0,
          borderTop: '1px solid rgba(0,0,0,0.08)',
          boxShadow: '0 -4px 20px rgba(0,0,0,0.1)',
          bgcolor: 'background.paper',
          zIndex: 1000,
          mt: 'auto'
        }}
      >
        <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'flex-end' }}>
          <Button
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={handleClearChat}
            size="medium"
            sx={{
              textTransform: 'none',
              fontWeight: 600,
              borderRadius: 2,
              borderColor: 'rgba(0,0,0,0.2)',
              color: '#667eea',
              whiteSpace: 'nowrap',
              minWidth: '140px',
              height: '48px',
              '&:hover': {
                bgcolor: 'rgba(102, 126, 234, 0.08)',
                borderColor: '#667eea'
              }
            }}
          >
            New Chat
          </Button>
          <TextField
            ref={inputRef}
            fullWidth
            multiline
            maxRows={4}
            placeholder="Ask me about your AWS costs... (e.g., 'Show me my top 5 cost drivers this month')"
            value={inputMessage}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setInputMessage(e.target.value)}
            onKeyPress={handleKeyPress}
            disabled={isLoading}
            variant="outlined"
            sx={{
              '& .MuiOutlinedInput-root': {
                borderRadius: 2,
                bgcolor: 'rgba(0,0,0,0.02)',
                fontSize: '0.95rem',
                transition: 'all 0.2s ease-in-out',
                '&:hover': {
                  bgcolor: 'rgba(0,0,0,0.03)',
                },
                '&.Mui-focused': {
                  bgcolor: 'white',
                  boxShadow: '0 0 0 3px rgba(102, 126, 234, 0.1)',
                  '& .MuiOutlinedInput-notchedOutline': {
                    borderColor: '#667eea',
                    borderWidth: '2px'
                  }
                },
                '& .MuiOutlinedInput-notchedOutline': {
                  borderColor: 'rgba(0,0,0,0.12)',
                }
              },
              '& .MuiInputBase-input': {
                py: 1.5,
                px: 2
              }
            }}
          />
          <IconButton
            onClick={handleSendMessage}
            disabled={!inputMessage.trim() || isLoading}
            sx={{
              bgcolor: '#667eea',
              background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              color: 'white',
              width: 48,
              height: 48,
              boxShadow: '0 4px 14px rgba(102, 126, 234, 0.4)',
              transition: 'all 0.2s ease-in-out',
              '&:hover': {
                bgcolor: '#5568d3',
                background: 'linear-gradient(135deg, #5568d3 0%, #653a8a 100%)',
                transform: 'translateY(-2px)',
                boxShadow: '0 6px 20px rgba(102, 126, 234, 0.5)',
              },
              '&:disabled': {
                bgcolor: 'rgba(0,0,0,0.12)',
                background: 'rgba(0,0,0,0.12)',
                color: 'rgba(0,0,0,0.26)',
                boxShadow: 'none'
              }
            }}
          >
            <SendIcon />
          </IconButton>
        </Box>
      </Paper>
    </Box>
  );
};

export default ChatInterface;
