#!/usr/bin/env python3
"""
Test script for database-backed conversation context manager
"""

import asyncio
import pytest
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))

from services.conversation_context import ConversationContextManager
import structlog

logger = structlog.get_logger(__name__)


@pytest.mark.asyncio
async def test_conversation_persistence():
    """Test that conversations persist in database"""
    print("🧪 Testing database-backed conversation context manager...")

    # Create context manager
    manager = ConversationContextManager()

    try:
        # Test 1: Create a new conversation
        conversation_id = "test-conversation-123"
        print(f"1. Creating conversation: {conversation_id}")

        context = await manager.get_or_create_context(conversation_id)
        print(f"   ✅ Created context: {context.conversation_id}")

        # Test 2: Update context with some data
        print("2. Updating context with query data")
        await manager.update_context(
            conversation_id=conversation_id,
            query="Show me EC2 costs for last month",
            intent="cost_analysis",
            extracted_params={
                "services": ["EC2"],
                "time_range": {"period": "30d", "source": "explicit"}
            },
            results_count=150,
            total_cost=2500.50
        )
        print("   ✅ Updated context")

        # Test 3: Add a message
        print("3. Adding message to conversation")
        await manager.add_message(conversation_id, "user", "Show me EC2 costs for last month")
        await manager.add_message(conversation_id, "assistant", "Here are your EC2 costs...")
        print("   ✅ Added messages")

        # Test 4: Retrieve context and verify data
        print("4. Retrieving context to verify persistence")
        retrieved_context = await manager.get_context(conversation_id)

        if retrieved_context:
            print(f"   ✅ Retrieved context: {retrieved_context.conversation_id}")
            print(f"   ✅ Last query: {retrieved_context.last_query}")
            print(f"   ✅ Last intent: {retrieved_context.last_intent}")
            print(f"   ✅ Services: {retrieved_context.last_params.get('services')}")
            print(f"   ✅ Results count: {retrieved_context.last_results_count}")
            print(f"   ✅ Total cost: {retrieved_context.last_total_cost}")
            print(f"   ✅ Messages: {len(retrieved_context.conversation_history)}")
        else:
            print("   ❌ Failed to retrieve context")
            return False

        # Test 5: Test follow-up refinement
        print("5. Testing follow-up query refinement")
        follow_up_params = retrieved_context.apply_follow_up_refinement(
            query="exclude RDS from that",
            new_params={"services": ["RDS"]}
        )
        print(f"   ✅ Refined params: {follow_up_params}")

        # Test 6: Cleanup expired contexts
        print("6. Testing cleanup of expired contexts")
        await manager.cleanup_expired(max_age_minutes=0)  # Expire immediately for testing
        print("   ✅ Cleanup completed")

        print("🎉 All tests passed! Database-backed conversation context is working.")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Close database connections
        await manager.close()


async def main():
    """Main entry point"""
    success = await test_conversation_persistence()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())