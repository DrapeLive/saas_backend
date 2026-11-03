from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.orders.tests.test_order_flow import OrderFixtureMixin
from config.asgi import application


class OrderConsumerTests(OrderFixtureMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.token = str(AccessToken.for_user(self.agent_user))

    async def _receive_action(self, communicator, action):
        for _ in range(10):
            message = await communicator.receive_json_from(timeout=2)
            if message.get("action") == action:
                return message
        self.fail(f"No response received for {action}")

    async def _draft_round_trip(self):
        communicator = WebsocketCommunicator(
            application,
            f"/ws/orders/?token={self.token}&company_id={self.company.id}",
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        hello = await communicator.receive_json_from(timeout=2)
        self.assertEqual(hello["event"], "connected")
        self.assertEqual(hello["data"]["company_id"], str(self.company.id))
        self.assertEqual(hello["data"]["drafts"], [])

        await communicator.send_json_to(
            {
                "action": "order.create",
                "request_id": "create-1",
                "payload": {"customer": str(self.customer.id)},
            }
        )
        created = await self._receive_action(communicator, "order.create")
        self.assertTrue(created["ok"], created)
        self.assertEqual(created["data"]["status"], "draft")
        order_id = created["data"]["id"]

        await communicator.send_json_to(
            {
                "action": "order.add_item",
                "request_id": "add-1",
                "payload": {
                    "order_id": order_id,
                    "color_variant": str(self.color.id),
                    "size_range": "20-24",
                    "quantity": 2,
                },
            }
        )
        added = await self._receive_action(communicator, "order.add_item")
        self.assertTrue(added["ok"], added)
        items = added["data"]["order"]["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual({item["size"] for item in items}, {"20", "22", "24"})
        self.assertEqual({item["quantity"] for item in items}, {2})
        self.assertEqual(len({item["group_id"] for item in items}), 1)

        await communicator.send_json_to(
            {
                "action": "order.submit",
                "request_id": "submit-1",
                "payload": {"order_id": order_id},
            }
        )
        submitted = await self._receive_action(communicator, "order.submit")
        self.assertTrue(submitted["ok"], submitted)
        self.assertEqual(submitted["data"]["status"], "submitted")
        self.assertIsNone(submitted["data"]["draft_expires_at"])

        await communicator.send_json_to(
            {"action": "order.drafts", "request_id": "drafts-1", "payload": {}}
        )
        drafts = await self._receive_action(communicator, "order.drafts")
        self.assertTrue(drafts["ok"], drafts)
        self.assertEqual(drafts["data"], [])

        await communicator.disconnect()

    def test_websocket_draft_round_trip(self):
        async_to_sync(self._draft_round_trip)()

    async def _unknown_action(self):
        communicator = WebsocketCommunicator(
            application,
            f"/ws/orders/?token={self.token}&company_id={self.company.id}",
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.receive_json_from(timeout=2)

        await communicator.send_json_to(
            {"action": "order.nope", "request_id": "x", "payload": {}}
        )
        response = await communicator.receive_json_from(timeout=2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "UNKNOWN_ACTION")
        await communicator.disconnect()

    def test_unknown_action_is_rejected(self):
        async_to_sync(self._unknown_action)()
