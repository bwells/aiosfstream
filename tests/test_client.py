from asynctest import TestCase, mock

from aiocometd.exceptions import ServerError, AiocometdException

from aiosfstream.client import Client, COMETD_PATH, API_VERSION
from aiosfstream.auth import AuthenticatorBase
from aiosfstream.replay import ReplayMarkerStorage, MappingStorage, \
    ConstantReplayId, ReplayOption
from aiosfstream.exceptions import AiosfstreamException


class TestGetCometdUrl(TestCase):
    def test_get(self):
        instance_url = "instance"

        result = Client.get_cometd_url(instance_url)

        self.assertEqual(result,
                         instance_url + "/" + COMETD_PATH + "/" + API_VERSION)


class TestClient(TestCase):
    def setUp(self):
        self.authenticator = mock.create_autospec(AuthenticatorBase)
        self.client = Client(self.authenticator)

    def test_init(self):
        connection_timeout = 20
        max_pending_count = 1
        loop = object()
        client = Client(self.authenticator,
                        connection_timeout=connection_timeout,
                        max_pending_count=max_pending_count,
                        loop=loop)

        self.assertEqual(client.url, "")
        self.assertEqual(client.auth, self.authenticator)
        self.assertEqual(client.connection_timeout, connection_timeout)
        self.assertEqual(client._max_pending_count, max_pending_count)
        self.assertEqual(client._loop, loop)

    @mock.patch("aiosfstream.client.CometdClient.__init__")
    def test_init_translates_errors(self, super_init):
        super_init.side_effect = AiocometdException()

        with self.assertRaises(AiosfstreamException):
            Client(self.authenticator)

    def test_init_vefiries_authenticator(self):
        with self.assertRaisesRegex(TypeError,
                                    f"authenticator should be an instance of "
                                    f"{AuthenticatorBase.__name__}."):
            Client(object())

    @mock.patch("aiosfstream.client.Client.create_replay_storage")
    def test_init_creates_replay_storage(self, create_replay_storage):
        replay_param = object()
        create_replay_storage.return_value = object()

        client = Client(self.authenticator,
                        replay=replay_param)

        self.assertEqual(client.auth, self.authenticator)
        self.assertEqual(client.extensions,
                         [create_replay_storage.return_value])
        self.assertEqual(client.replay_storage,
                         create_replay_storage.return_value)
        self.assertIsNone(client.replay_fallback)
        create_replay_storage.assert_called_with(replay_param)

    @mock.patch("aiosfstream.client.Client.create_replay_storage")
    def test_init_none_replay_storage(self, create_replay_storage):
        replay_param = object()
        create_replay_storage.return_value = None

        client = Client(self.authenticator,
                        replay=replay_param)

        self.assertEqual(client.auth, self.authenticator)
        self.assertIsNone(client.extensions)
        self.assertIsNone(client.replay_storage)
        self.assertIsNone(client.replay_fallback)
        create_replay_storage.assert_called_with(replay_param)

    @mock.patch("aiosfstream.client.CometdClient.open")
    @mock.patch("aiosfstream.client.Client.get_cometd_url")
    async def test_open(self, get_cometd_url, super_open):
        get_cometd_url.return_value = "url"

        await self.client.open()

        self.authenticator.authenticate.assert_called()
        self.assertEqual(self.client.url, get_cometd_url.return_value)
        super_open.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.open")
    @mock.patch("aiosfstream.client.Client.get_cometd_url")
    async def test_open_translates_errors(self, get_cometd_url, super_open):
        get_cometd_url.return_value = "url"
        super_open.side_effect = AiocometdException()

        with self.assertRaises(AiosfstreamException):
            await self.client.open()

    @mock.patch("aiosfstream.client.CometdClient.close")
    async def test_close(self, super_close):
        await self.client.close()

        super_close.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.close")
    async def test_close_translates_errors(self, super_close):
        super_close.side_effect = AiocometdException()

        with self.assertRaises(AiosfstreamException):
            await self.client.close()

    @mock.patch("aiosfstream.client.CometdClient.subscribe")
    async def test_subscribe_successful(self, super_subscribe):
        channel = "/foo/bar"

        await self.client.subscribe(channel)

        super_subscribe.assert_called_with(channel)

    @mock.patch("aiosfstream.client.CometdClient.subscribe")
    async def test_subscribe_error_with_fallback_and_storage(self,
                                                             super_subscribe):
        channel = "/foo/bar"
        self.client.replay_fallback = object()
        self.client.replay_storage = mock.MagicMock()
        error = ServerError("message", {"error": "400::"})
        super_subscribe.side_effect = [error, None]

        await self.client.subscribe(channel)

        super_subscribe.assert_has_calls([mock.call(channel)] * 2)
        self.assertEqual(self.client.replay_storage.replay_fallback,
                         self.client.replay_fallback)

    @mock.patch("aiosfstream.client.CometdClient.subscribe")
    async def test_subscribe_error_without_fallback_and_storage(
            self, super_subscribe):
        channel = "/foo/bar"
        self.client.replay_fallback = None
        self.client.replay_storage = mock.MagicMock()
        self.client.replay_storage.replay_fallback = None
        error = ServerError("message", {"error": "400::"})
        super_subscribe.side_effect = [error, None]

        with self.assertRaises(ServerError):
            await self.client.subscribe(channel)

        super_subscribe.assert_called_with(channel)
        self.assertIsNone(self.client.replay_storage.replay_fallback)

    @mock.patch("aiosfstream.client.CometdClient.subscribe")
    async def test_subscribe_error_with_fallback_without_storage(
            self, super_subscribe):
        channel = "/foo/bar"
        self.client.replay_fallback = object()
        self.client.replay_storage = None
        error = ServerError("message", {"error": "400::"})
        super_subscribe.side_effect = [error, None]

        with self.assertRaises(ServerError):
            await self.client.subscribe(channel)

        super_subscribe.assert_called_with(channel)

    @mock.patch("aiosfstream.client.CometdClient.subscribe")
    async def test_subscribe_different_error_with_fallback_and_storage(
            self, super_subscribe):
        channel = "/foo/bar"
        self.client.replay_fallback = object()
        self.client.replay_storage = mock.MagicMock()
        self.client.replay_storage.replay_fallback = None
        error = ServerError("message", {"error": "401::"})
        super_subscribe.side_effect = [error, None]

        with self.assertRaises(ServerError):
            await self.client.subscribe(channel)

        super_subscribe.assert_called_with(channel)
        self.assertIsNone(self.client.replay_storage.replay_fallback)

    @mock.patch("aiosfstream.client.CometdClient.subscribe")
    async def test_subscribe_translates_errors(self, super_subscribe):
        super_subscribe.side_effect = AiocometdException()
        channel = "/foo/bar"

        with self.assertRaises(AiosfstreamException):
            await self.client.subscribe(channel)

        super_subscribe.assert_called_with(channel)

    @mock.patch("aiosfstream.client.CometdClient.unsubscribe")
    async def test_unsubscribe(self, super_unsubscribe):
        channel = "/foo/bar"

        await self.client.unsubscribe(channel)

        super_unsubscribe.assert_called_with(channel)

    @mock.patch("aiosfstream.client.CometdClient.unsubscribe")
    async def test_unsubscribe_translates_errors(self, super_unsubscribe):
        super_unsubscribe.side_effect = AiocometdException()
        channel = "/foo/bar"

        with self.assertRaises(AiosfstreamException):
            await self.client.unsubscribe(channel)

        super_unsubscribe.assert_called_with(channel)

    @mock.patch("aiosfstream.client.CometdClient.publish")
    async def test_publish(self, super_publish):
        channel = "/foo/bar"
        super_publish.return_value = object()
        data = object()

        result = await self.client.publish(channel, data)

        self.assertEqual(result, super_publish.return_value)
        super_publish.assert_called_with(channel, data)

    @mock.patch("aiosfstream.client.CometdClient.publish")
    async def test_publish_translates_errors(self, super_publish):
        super_publish.side_effect = AiocometdException()
        channel = "/foo/bar"
        data = object()

        with self.assertRaises(AiosfstreamException):
            await self.client.publish(channel, data)

        super_publish.assert_called_with(channel, data)

    @mock.patch("aiosfstream.client.CometdClient.receive")
    async def test_receive(self, super_receive):
        super_receive.return_value = object()

        result = await self.client.receive()

        self.assertEqual(result, super_receive.return_value)
        super_receive.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.receive")
    async def test_receive_translates_errors(self, super_receive):
        super_receive.side_effect = AiocometdException()

        with self.assertRaises(AiosfstreamException):
            await self.client.receive()

        super_receive.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.__aiter__")
    async def test_aiter(self, super_aiter):
        super_aiter.return_value = object()

        result = await self.client.__aiter__()

        self.assertEqual(result, super_aiter.return_value)
        super_aiter.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.__aiter__")
    async def test_aiter_translates_errors(self, super_aiter):
        super_aiter.side_effect = AiocometdException()

        with self.assertRaises(AiosfstreamException):
            await self.client.__aiter__()

        super_aiter.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.__aenter__")
    async def test_aenter(self, super_aenter):
        super_aenter.return_value = object()

        result = await self.client.__aenter__()

        self.assertEqual(result, super_aenter.return_value)
        super_aenter.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.__aenter__")
    async def test_aenter_translates_errors(self, super_aenter):
        super_aenter.side_effect = AiocometdException()

        with self.assertRaises(AiosfstreamException):
            await self.client.__aenter__()

        super_aenter.assert_called()

    @mock.patch("aiosfstream.client.CometdClient.__aexit__")
    async def test_aexit(self, super_aexit):
        super_aexit.return_value = object()
        args = [1, 2, 3]

        result = await self.client.__aexit__(*args)

        self.assertEqual(result, super_aexit.return_value)
        super_aexit.assert_called_with(*args)

    @mock.patch("aiosfstream.client.CometdClient.__aexit__")
    async def test_aexit_translates_errors(self, super_aexit):
        super_aexit.side_effect = AiocometdException()
        args = [1, 2, 3]

        with self.assertRaises(AiosfstreamException):
            await self.client.__aexit__(*args)

        super_aexit.assert_called_with(*args)


class TestCreateReplayStorage(TestCase):
    def test_returns_replay_storage(self):
        replay = mock.create_autospec(ReplayMarkerStorage)()

        result = Client.create_replay_storage(replay)

        self.assertIs(result, replay)

    def test_returns_mapping_storage_for_dict(self):
        replay = {}

        result = Client.create_replay_storage(replay)

        self.assertIsInstance(result, MappingStorage)
        self.assertIs(result.mapping, replay)

    def test_returns_constant_replay_id_storage_for_replay_option(self):
        replay = ReplayOption.ALL_EVENTS

        result = Client.create_replay_storage(replay)

        self.assertIsInstance(result, ConstantReplayId)
        self.assertIs(result.default_id, replay)

    def test_returns_none_for_none_param(self):
        replay = None

        result = Client.create_replay_storage(replay)

        self.assertIsNone(result)
