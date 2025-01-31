import json
from unittest.mock import MagicMock, patch

import pytest
from langchain.callbacks.base import BaseCallbackHandler

from genai import Credentials
from genai.schemas import GenerateParams
from genai.schemas.responses import GenerateResponse
from genai.services import ServiceInterface
from tests.assets.response_helper import SimpleResponse


@pytest.mark.extension
class TestLangChain:
    def setup_method(self):
        self.service = ServiceInterface(service_url="SERVICE_URL", api_key="API_KEY")
        self.model = "google/ul2"
        self.inputs = ["Write a tagline for an alumni association: Together we"]

    @pytest.fixture
    def credentials(self):
        return Credentials("GENAI_APY_KEY")

    @pytest.fixture
    def params(self):
        return GenerateParams()

    @pytest.fixture
    def prompts(self):
        return ["Hi! How's the weather, eh?"]

    @pytest.fixture
    def multi_prompts(self):
        return ["What is IBM?", "What is AI?"]

    @patch("httpx.AsyncClient.post")
    def test_langchain_interface(
        self,
        mocked_post_request,
        credentials,
        params,
        prompts,
    ):
        from genai.extensions.langchain import LangChainInterface

        GENERATE_RESPONSE = SimpleResponse.generate(model="google/flan-ul2", inputs=prompts, params=params)
        expected_generated_response = GenerateResponse(**GENERATE_RESPONSE)

        response = MagicMock(status_code=200)
        response.json.return_value = GENERATE_RESPONSE
        mocked_post_request.return_value = response

        model = LangChainInterface(model="google/flan-ul2", params=params, credentials=credentials)
        results = model(prompts[0])
        assert results == expected_generated_response.results[0].generated_text

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_async_langchain_interface(self, mocked_post_request, credentials, params, multi_prompts):
        from genai.extensions.langchain import LangChainInterface

        expected_responses = []
        mock_responses = []
        for prompt in multi_prompts:
            server_response = SimpleResponse.generate(model="google/flan-ul2", inputs=[prompt], params=params)
            expected_response = GenerateResponse(**server_response)
            expected_responses.append(expected_response)

            mock_response = MagicMock(status_code=200)
            mock_response.json.return_value = server_response
            mock_responses.append(mock_response)

        mocked_post_request.side_effect = mock_responses

        model = LangChainInterface(model="google/flan-ul2", params=params, credentials=credentials)
        observed = await model.agenerate(prompts=multi_prompts)
        assert len(observed.generations) == 2
        assert len(observed.generations[0]) == 1
        assert len(observed.generations[1]) == 1

        assert observed.llm_output["token_usage"]["input_token_count"] == sum(
            c.results[0].input_token_count for c in expected_responses
        )
        assert observed.llm_output["token_usage"]["generated_token_count"] == sum(
            c.results[0].generated_token_count for c in expected_responses
        )

        for idx, generation_list in enumerate(observed.generations):
            assert len(generation_list) == 1
            generation = generation_list[0]
            assert generation.text == expected_responses[idx].results[0].generated_text

            expected_result = expected_responses[idx].results[0].dict()
            for key in {"generated_token_count", "input_text", "stop_reason"}:
                assert generation.generation_info[key] == expected_result[key]

    @patch("genai.services.RequestHandler.post_stream")
    def test_langchain_stream(self, mock_post_stream, credentials, params, prompts):
        from genai.extensions.langchain import LangChainInterface

        GENERATE_STREAM_RESPONSES = SimpleResponse.generate_stream(
            model="google/flan-ul2", inputs=prompts, params=params
        )

        response = MagicMock(status_code=200)
        response.__iter__.return_value = (f"data: {json.dumps(response)}" for response in GENERATE_STREAM_RESPONSES)
        mock_post_stream.return_value = response

        callback = BaseCallbackHandler()
        callback.on_llm_new_token = MagicMock()

        model = LangChainInterface(
            model="google/flan-ul2",
            params=params,
            credentials=credentials,
            callbacks=[callback],
        )
        expected_generated_responses = [GenerateResponse(**result) for result in GENERATE_STREAM_RESPONSES]

        # Verify results
        for idx, result in enumerate(model.stream(input=prompts[0])):
            expected_result = expected_generated_responses[idx]
            assert result == expected_result.results[0].generated_text

        # Verify that callbacks were called
        assert callback.on_llm_new_token.call_count == len(expected_generated_responses)
        for idx, result in enumerate(expected_generated_responses):
            retrieved_kwargs = callback.on_llm_new_token.call_args_list[idx].kwargs
            token = retrieved_kwargs["token"]
            assert token == result.results[0].generated_text
            response = retrieved_kwargs["response"]
            assert response == result.results[0]

    def test_prompt_translator(self):
        from langchain import PromptTemplate

        import genai.extensions.langchain  # noqa
        from genai.prompt_pattern import PromptPattern

        s = "My name is {name}. I work for {company}. I live in {city}."
        pt = PromptTemplate(input_variables=["name", "company", "city"], template=s)
        pattern = PromptPattern.langchain.from_template(pt)
        assert pattern.find_vars() == {"name", "company", "city"}
        ptemp = pattern.langchain.as_template()
        assert set(ptemp.input_variables) == {"name", "company", "city"}
        assert ptemp.template == s
