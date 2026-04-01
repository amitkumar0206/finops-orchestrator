# Deploy Demo Control Panel via AWS Console

Since IAM permissions are being complex, here's the step-by-step **manual console approach** to create API Gateway + Lambda integration.

## Prerequisites

✓ Lambda function `aasmaa-demo-control` is already deployed (with handler.py and env vars)  
✓ Token is saved in `.control-token` file  
✓ You have AWS Console access

---

## Steps

### 1. Create HTTP API in API Gateway

1. Go to **AWS Console** → **API Gateway** → **APIs**
2. Click **Create API**
3. Choose **HTTP API** (not REST API)
4. Fill in:
   - **Name**: `aasmaa-demo-control`
   - **Integrations**: Click "Add an integration" → **Lambda** → select `aasmaa-demo-control` function
5. Click **Create**

### 2. Create integration (if not already done)

1. In the API, go to **Integrations** (left sidebar)
2. If you don't see `aasmaa-demo-control`, click **Create and attach to a route**
3. Select **Lambda** → `aasmaa-demo-control`
4. Click **Create integration**

### 3. Create catch-all route

1. Go to **Routes** (left sidebar)
2. Click **Create**
3. **Method + path**: Select `$default` (this matches all requests)
4. **Integration target**: Select the `aasmaa-demo-control` Lambda from the dropdown
5. Click **Create**

### 4. Create deployment stage

1. Go to **Stages** (left sidebar)
2. Click **Create**
3. **Stage name**: `demo`
4. Click **Create**
5. Copy the **Invoke URL** — this is your endpoint

### 5. Get your shareable URL

Your endpoint looks like:
```
https://abc1234xyz.execute-api.us-east-1.amazonaws.com/demo
```

Your **shareable URL** is:
```
https://abc1234xyz.execute-api.us-east-1.amazonaws.com/demo?token=<TOKEN>
```

Get the token:
```bash
cat scripts/demo/lambda-control/.control-token
```

---

## Test it

```bash
# Replace with your actual URL
curl "https://abc1234xyz.execute-api.us-east-1.amazonaws.com/demo?token=32842edbe85f40fc83ed1f703883b8bc"
```

You should see HTML (the control panel page).

---

## Cost

- **API Gateway**: $0.50/month (3.5M free requests, then $0.35/M)
- **Lambda**: Free tier (~1M requests/month)
- **Total**: essentially $0 for your use case

---

## Share the URL

Once you have the endpoint, share this with your team:
```
https://abc1234xyz.execute-api.us-east-1.amazonaws.com/demo?token=<YOUR_TOKEN>
```

They can:
- ✓ See service status (refreshes every 15 sec)
- ✓ Click **Start Services** to scale ECS to 1 task
- ✓ Click **Stop Services** to scale ECS to 0 tasks  
- ✓ See real-time logs of what happened

---

## Update Lambda code later

If you change `handler.py`, just run:
```bash
cd scripts/demo/lambda-control
./deploy-apigw.sh
```

The API endpoint stays the same — Lambda code is updated in-place.

---

## Rotate the token

To generate a new token (e.g., if someone leaves):
```bash
rm scripts/demo/lambda-control/.control-token
./deploy-apigw.sh
# New URL will be printed
```

---

## Cleanup

To delete everything:
```bash
./teardown.sh  # Removes Lambda + IAM role
```

Then in the console, go to **API Gateway** → **aasmaa-demo-control** → **Delete API**

---

That's it! The console UI is straightforward for these 5 steps.
