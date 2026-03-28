from channels.generic.websocket import AsyncJsonWebsocketConsumer


class TenantEventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        route_tenant_id = (self.scope.get('url_route', {}).get('kwargs', {}).get('tenant_id') or '').strip().lower()
        token_tenant_id = (self.scope.get('tenant_id') or '').strip().lower()

        if not user or getattr(user, 'is_anonymous', True):
            await self.close(code=4401)
            return

        if not route_tenant_id or route_tenant_id != token_tenant_id:
            await self.close(code=4403)
            return

        self.group_name = f"tenant-events-{route_tenant_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({
            'type': 'connection.ready',
            'tenant_id': route_tenant_id,
        })

    async def disconnect(self, close_code):
        group_name = getattr(self, 'group_name', '')
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if (content or {}).get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def tenant_event(self, event):
        await self.send_json({
            'type': event.get('event', 'tenant.event'),
            'topic': event.get('topic', ''),
            'tenant_id': event.get('tenant_id', ''),
            'payload': event.get('payload', {}),
            'timestamp': event.get('timestamp', ''),
        })