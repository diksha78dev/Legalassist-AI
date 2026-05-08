# JavaScript SDK for Legalassist-AI

Complete JavaScript/TypeScript SDK for integrating with Legalassist-AI REST API.

## Installation

```bash
npm install legalassist-sdk
# or yarn
yarn add legalassist-sdk
```

## Quick Start

```javascript
import LegalassistClient from 'legalassist-sdk';

const client = new LegalassistClient({ apiKey: 'your-api-key' });

// Analyze document
const result = await client.analyzeDocument({ text: 'Contract text...' });
console.log('Job ID:', result.job_id);

// Wait for result
const analysis = await client.waitForAnalysis(result.job_id);
console.log('Summary:', analysis.summary);
```

## Features

- ✅ Promise-based async API
- ✅ TypeScript support
- ✅ Automatic retries
- ✅ WebSocket support
- ✅ Browser and Node.js compatible
- ✅ Comprehensive error handling
- ✅ Rate limit handling

## Examples

### Document Analysis

```javascript
// Analyze from text
const result = await client.analyzeDocument({
  text: 'Full contract text...',
  documentType: 'contract'
});

// Or from file URL
const result = await client.analyzeDocument({
  fileUrl: 'https://example.com/contract.pdf',
  documentType: 'contract'
});

// Wait for result
const analysis = await client.waitForAnalysis(result.job_id);
console.log(analysis.summary);
console.log(analysis.remedies);
```

### Case Search

```javascript
const results = await client.searchCases({
  keywords: ['breach of contract', 'damages'],
  jurisdiction: 'US',
  limit: 20
});

results.results.forEach(case => {
  console.log(`${case.case_number}: ${case.title}`);
});
```

### Report Generation

```javascript
// Generate report
const report = await client.generateReport({
  caseId: 'case_123',
  reportType: 'comprehensive',
  format: 'pdf'
});

// Wait and get download link
const downloadUrl = await client.waitForReport(report.report_id);
console.log('Download:', downloadUrl);
```

### Deadlines

```javascript
// Get upcoming deadlines
const deadlines = await client.getUpcomingDeadlines(30);

deadlines.deadlines
  .filter(d => d.priority === 'critical')
  .forEach(d => console.log(`🔴 ${d.title}`));

// Create deadline
const newDeadline = await client.createDeadline({
  title: 'Appeal Filing',
  dueDate: '2024-06-08T00:00:00Z',
  priority: 'high'
});
```

### Real-time Progress Tracking

```javascript
// Connect WebSocket for live progress
const ws = client.connectProgress(jobId, (data) => {
  console.log(`Progress: ${data.progress}%`);
  console.log(`Status: ${data.status}`);
  
  if (data.status === 'completed') {
    console.log('Analysis complete!');
  }
});

// Or manually disconnect
// ws.close();
```

## Authentication

### API Key

```javascript
const client = new LegalassistClient({ apiKey: 'sk_live_...' });
```

### JWT Token

```javascript
// Get token first
const tokenResponse = await client.getToken(
  'user@example.com',
  'password'
);

// Use token
const client = new LegalassistClient({ 
  token: tokenResponse.access_token 
});
```

## Usage in React

```jsx
import { useEffect, useState } from 'react';
import LegalassistClient from 'legalassist-sdk';

function DocumentAnalysis() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const client = new LegalassistClient({ apiKey: process.env.REACT_APP_API_KEY });

  const handleAnalyze = async (text) => {
    setLoading(true);
    const result = await client.analyzeDocument({ text });
    setResult(result);
    
    // Wait for completion
    const analysis = await client.waitForAnalysis(result.job_id);
    setResult(analysis);
    setLoading(false);
  };

  return (
    <div>
      <textarea onChange={(e) => text = e.target.value} />
      <button onClick={() => handleAnalyze(text)} disabled={loading}>
        {loading ? 'Analyzing...' : 'Analyze'}
      </button>
      {result && <pre>{JSON.stringify(result, null, 2)}</pre>}
    </div>
  );
}

export default DocumentAnalysis;
```

## TypeScript Support

```typescript
import LegalassistClient, { 
  AnalysisRequest, 
  AnalysisResult 
} from 'legalassist-sdk';

const client = new LegalassistClient({ apiKey: 'your-key' });

const analyze = async (text: string): Promise<AnalysisResult> => {
  const request: AnalysisRequest = { text, documentType: 'contract' };
  const result = await client.analyzeDocument(request);
  return client.waitForAnalysis(result.job_id);
};
```

## Error Handling

```javascript
try {
  const result = await client.analyzeDocument({ text: '...' });
} catch (error) {
  if (error.response?.status === 429) {
    console.log('Rate limited! Retry after:', error.response.headers['retry-after']);
  } else if (error.response?.status === 401) {
    console.log('Invalid credentials');
  } else {
    console.error('Error:', error.message);
  }
}
```

## API Reference

### Methods

- `getToken(username, password)` - Get access token
- `createApiKey(name, expiresInDays)` - Create API key
- `getCurrentUser()` - Get user info
- `analyzeDocument(options)` - Analyze document
- `getAnalysisStatus(jobId)` - Check status
- `getAnalysisResult(jobId)` - Get result
- `waitForAnalysis(jobId, options)` - Wait for completion
- `searchCases(options)` - Search cases
- `getCaseTimeline(caseId)` - Get timeline
- `generateReport(options)` - Generate report
- `getReportStatus(reportId)` - Check status
- `waitForReport(reportId, options)` - Wait for report
- `getUpcomingDeadlines(days)` - Get deadlines
- `createDeadline(options)` - Create deadline
- `getCostBreakdown(period)` - Get costs
- `getAnalyticsOverview()` - Get analytics
- `connectProgress(jobId, callback)` - WebSocket progress

## Browser Usage

```html
<script src="https://cdn.example.com/legalassist-sdk.js"></script>
<script>
  const client = new LegalassistClient({ apiKey: 'your-key' });
  
  document.querySelector('#analyze-btn').addEventListener('click', async () => {
    const text = document.querySelector('#document-input').value;
    const result = await client.analyzeDocument({ text });
    console.log('Job ID:', result.job_id);
  });
</script>
```

## Support

- **Issue Tracker**: [GitHub Issues](https://github.com/legalassist-ai/sdk-javascript)
- **Documentation**: [API Docs](/docs)
- **Email**: sdk-support@example.com
