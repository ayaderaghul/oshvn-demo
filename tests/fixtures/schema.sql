-- Test fixture: the schema the app reads, from a disposable Postgres built by oshvn_loader's verify skill
-- (Neon base tables + loader migrations 003-005) plus explain_rule() copied from Neon on 2026-11-11.
-- Regenerate: oshvn_loader verify.py up, load explain_rule, then pg_dump --schema-only --no-owner --no-privileges.
--
-- PostgreSQL database dump
--

\restrict 2oV7Fjq7ZVHvWz0jfnEbsFTHVWiUGyvZjLRXjIN45IeV99ficJhbFeyT3n5Xr1b

-- Dumped from database version 17.11 (Debian 17.11-1.pgdg12+2)
-- Dumped by pg_dump version 17.11 (Debian 17.11-1.pgdg12+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: unaccent; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;


--
-- Name: EXTENSION unaccent; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION unaccent IS 'text search dictionary that removes accents';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: explain_rule(jsonb, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.explain_rule(rule jsonb, profile jsonb) RETURNS jsonb
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE r jsonb; sub jsonb; reasons jsonb := '[]'::jsonb; missing jsonb := '[]'::jsonb; f text; op text; val jsonb; actual jsonb; hit jsonb;
BEGIN
  IF rule ? 'always' THEN
    RETURN jsonb_build_object('applies', (rule->>'always')::boolean, 'reasons', jsonb_build_array('applies to every employer'), 'missing', '[]'::jsonb);
  ELSIF rule ? 'all' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(rule->'all') LOOP
      sub := explain_rule(r, profile);
      IF NOT (sub->>'applies')::boolean THEN
        RETURN jsonb_build_object('applies', false, 'reasons', '[]'::jsonb, 'missing', sub->'missing');
      END IF;
      reasons := reasons || (sub->'reasons');
    END LOOP;
    RETURN jsonb_build_object('applies', true, 'reasons', reasons, 'missing', '[]'::jsonb);
  ELSIF rule ? 'any' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(rule->'any') LOOP
      sub := explain_rule(r, profile);
      IF (sub->>'applies')::boolean THEN RETURN sub; END IF;
      missing := missing || (sub->'missing');
    END LOOP;
    RETURN jsonb_build_object('applies', false, 'reasons', '[]'::jsonb, 'missing', missing);
  ELSIF rule ? 'not' THEN
    sub := explain_rule(rule->'not', profile);
    IF (sub->>'applies')::boolean THEN
      RETURN jsonb_build_object('applies', false, 'reasons', '[]'::jsonb, 'missing', jsonb_build_array('excluded because: ' || (sub->'reasons')::text));
    END IF;
    RETURN jsonb_build_object('applies', true, 'reasons', jsonb_build_array('exclusion does not apply'), 'missing', '[]'::jsonb);
  END IF;

  f := rule->>'field'; op := rule->>'op'; val := rule->'value'; actual := profile->f;
  IF op = 'contains_any' THEN
    SELECT jsonb_agg(a.value) INTO hit
      FROM jsonb_array_elements(CASE WHEN jsonb_typeof(actual) = 'array' THEN actual ELSE '[]'::jsonb END) a
     WHERE val @> jsonb_build_array(a.value);
    IF hit IS NOT NULL THEN
      RETURN jsonb_build_object('applies', true, 'reasons', jsonb_build_array(f || ' include ' || hit::text), 'missing', '[]'::jsonb);
    END IF;
    RETURN jsonb_build_object('applies', false, 'reasons', '[]'::jsonb, 'missing', jsonb_build_array(f || ' would need one of ' || val::text));
  ELSIF op = 'not_empty' THEN
    IF jsonb_typeof(actual) = 'array' AND jsonb_array_length(actual) > 0 THEN
      RETURN jsonb_build_object('applies', true, 'reasons', jsonb_build_array(f || ' recorded: ' || actual::text), 'missing', '[]'::jsonb);
    END IF;
    RETURN jsonb_build_object('applies', false, 'reasons', '[]'::jsonb, 'missing', jsonb_build_array('no ' || f || ' recorded'));
  END IF;

  IF rule_matches(rule, profile) THEN
    RETURN jsonb_build_object('applies', true, 'reasons', jsonb_build_array(f || ' = ' || coalesce(actual::text, 'null') || ' (' || op || ' ' || val::text || ')'), 'missing', '[]'::jsonb);
  END IF;
  RETURN jsonb_build_object('applies', false, 'reasons', '[]'::jsonb, 'missing', jsonb_build_array(f || ' = ' || coalesce(actual::text, 'missing') || ', needs ' || op || ' ' || val::text));
END $$;


--
-- Name: review_proposal(integer, text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.review_proposal(p_id integer, p_decision text, p_by text, p_note text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
  IF p_decision NOT IN ('approved', 'rejected') THEN
    RAISE EXCEPTION 'quyết định không hợp lệ: %', p_decision;
  END IF;
  IF coalesce(trim(p_by), '') = '' THEN
    RAISE EXCEPTION 'cần tên người duyệt';
  END IF;
  UPDATE load_proposals
     SET status = p_decision, reviewed_by = left(trim(p_by), 100), reviewed_at = now(), review_note = left(p_note, 2000)
   WHERE id = p_id AND status = 'pending';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'đề xuất % không còn ở trạng thái chờ duyệt', p_id;
  END IF;
  RETURN p_decision;
END $$;


--
-- Name: review_proposal_items(integer, text, text, text, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.review_proposal_items(p_id integer, p_decision text, p_by text, p_note text, p_excluded jsonb) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
BEGIN
  IF p_decision NOT IN ('approved', 'rejected') THEN RAISE EXCEPTION 'quyết định không hợp lệ: %', p_decision; END IF;
  IF coalesce(trim(p_by), '') = '' THEN RAISE EXCEPTION 'cần tên người duyệt'; END IF;
  IF p_excluded IS NOT NULL AND jsonb_typeof(p_excluded) <> 'array' THEN RAISE EXCEPTION 'danh sách loại không hợp lệ'; END IF;
  UPDATE load_proposals
     SET status = p_decision, reviewed_by = left(trim(p_by), 100), reviewed_at = now(), review_note = left(p_note, 2000),
         excluded = p_excluded
   WHERE id = p_id AND status = 'pending';
  IF NOT FOUND THEN RAISE EXCEPTION 'đề xuất % không còn ở trạng thái chờ duyệt', p_id; END IF;
  RETURN p_decision;
END $$;


--
-- Name: rule_matches(jsonb, jsonb); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.rule_matches(rule jsonb, profile jsonb) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
DECLARE r jsonb; f text; op text; actual jsonb; val jsonb;
BEGIN
  IF rule ? 'all' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(rule->'all') LOOP
      IF NOT rule_matches(r, profile) THEN RETURN false; END IF;
    END LOOP;
    RETURN true;
  ELSIF rule ? 'any' THEN
    FOR r IN SELECT value FROM jsonb_array_elements(rule->'any') LOOP
      IF rule_matches(r, profile) THEN RETURN true; END IF;
    END LOOP;
    RETURN false;
  ELSIF rule ? 'not' THEN
    RETURN NOT rule_matches(rule->'not', profile);
  ELSIF rule ? 'always' THEN
    RETURN (rule->>'always')::boolean;
  END IF;
  f := rule->>'field'; op := rule->>'op'; val := rule->'value'; actual := profile->f;
  IF actual IS NULL THEN RETURN false; END IF;
  CASE op
    WHEN '='  THEN RETURN actual = val;
    WHEN '!=' THEN RETURN actual <> val;
    WHEN '>=' THEN RETURN (actual #>> '{}')::numeric >= (val #>> '{}')::numeric;
    WHEN '<'  THEN RETURN (actual #>> '{}')::numeric <  (val #>> '{}')::numeric;
    WHEN '<=' THEN RETURN (actual #>> '{}')::numeric <= (val #>> '{}')::numeric;
    WHEN 'in' THEN RETURN val @> jsonb_build_array(actual);
    WHEN 'contains_any' THEN RETURN EXISTS (SELECT 1 FROM jsonb_array_elements(actual) a WHERE val @> jsonb_build_array(a.value));
    WHEN 'not_empty' THEN RETURN jsonb_typeof(actual) = 'array' AND jsonb_array_length(actual) > 0;
    ELSE RAISE EXCEPTION 'unknown operator %', op;
  END CASE;
END $$;


--
-- Name: vi_simple; Type: TEXT SEARCH CONFIGURATION; Schema: public; Owner: -
--

CREATE TEXT SEARCH CONFIGURATION public.vi_simple (
    PARSER = pg_catalog."default" );

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR asciiword WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR word WITH public.unaccent, simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR numword WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR email WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR url WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR host WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR sfloat WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR version WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR hword_numpart WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR hword_part WITH public.unaccent, simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR hword_asciipart WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR numhword WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR asciihword WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR hword WITH public.unaccent, simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR url_path WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR file WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR "float" WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR "int" WITH simple;

ALTER TEXT SEARCH CONFIGURATION public.vi_simple
    ADD MAPPING FOR uint WITH simple;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chunks (
    id integer NOT NULL,
    source_kind text NOT NULL,
    document_id integer,
    file_id integer,
    client_profile_id integer,
    locator jsonb NOT NULL,
    text text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('public.vi_simple'::regconfig, text)) STORED,
    embedding public.vector(1024),
    embedding_model text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    text_sha256 text,
    load_run_id integer,
    retired boolean DEFAULT false NOT NULL,
    CONSTRAINT chunks_source_kind_check CHECK ((source_kind = ANY (ARRAY['legal_article'::text, 'transcript_segment'::text, 'photo_caption'::text, 'client_document'::text]))),
    CONSTRAINT legal_is_shared CHECK ((((source_kind = 'legal_article'::text) AND (client_profile_id IS NULL) AND (document_id IS NOT NULL)) OR ((source_kind <> 'legal_article'::text) AND (client_profile_id IS NOT NULL))))
);


--
-- Name: chunks_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chunks_history (
    chunk_id integer NOT NULL,
    text text NOT NULL,
    text_sha256 text,
    replaced_at timestamp with time zone DEFAULT now() NOT NULL,
    load_run_id integer
);


--
-- Name: chunks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.chunks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chunks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.chunks_id_seq OWNED BY public.chunks.id;


--
-- Name: legal_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.legal_documents (
    id integer NOT NULL,
    number text NOT NULL,
    type text NOT NULL,
    title_vi text,
    title_en text,
    effective_from date,
    status text DEFAULT 'to_verify'::text NOT NULL,
    notes text,
    source_url text,
    source_file text,
    source_sha256 text,
    parser_version text,
    check_report jsonb,
    load_run_id integer,
    CONSTRAINT legal_documents_type_check CHECK ((type = ANY (ARRAY['law'::text, 'decree'::text, 'circular'::text, 'standard'::text, 'resolution'::text, 'decision'::text, 'other'::text])))
);


--
-- Name: legal_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.legal_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: legal_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.legal_documents_id_seq OWNED BY public.legal_documents.id;


--
-- Name: load_proposals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.load_proposals (
    id integer NOT NULL,
    doc_code text NOT NULL,
    file_name text,
    source_sha256 text,
    parser_version text,
    options jsonb,
    payload jsonb NOT NULL,
    report jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_by text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    review_note text,
    applied_at timestamp with time zone,
    applied_run_id integer,
    apply_report jsonb,
    kind text DEFAULT 'documents'::text NOT NULL,
    excluded jsonb,
    CONSTRAINT load_proposals_kind_check CHECK ((kind = ANY (ARRAY['documents'::text, 'obligations'::text]))),
    CONSTRAINT load_proposals_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'applied'::text, 'superseded'::text, 'failed'::text])))
);


--
-- Name: load_proposals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.load_proposals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: load_proposals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.load_proposals_id_seq OWNED BY public.load_proposals.id;


--
-- Name: load_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.load_runs (
    id integer NOT NULL,
    kind text NOT NULL,
    parser_version text,
    embedding_model text,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    status text DEFAULT 'running'::text NOT NULL,
    report jsonb,
    created_by text,
    CONSTRAINT load_runs_kind_check CHECK ((kind = ANY (ARRAY['documents'::text, 'obligations'::text, 'embeddings'::text]))),
    CONSTRAINT load_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'applied'::text, 'rejected'::text, 'dry_run'::text])))
);


--
-- Name: load_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.load_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: load_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.load_runs_id_seq OWNED BY public.load_runs.id;


--
-- Name: obligations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.obligations (
    id text NOT NULL,
    document_id integer NOT NULL,
    article_ref text,
    category text NOT NULL,
    duty_vi text,
    duty_en text,
    responsible_party text,
    frequency text,
    evidence_required text,
    typical_hours numeric,
    applies_when jsonb NOT NULL,
    verification_status text DEFAULT 'sample_unverified'::text NOT NULL,
    last_verified_by text,
    last_verified_on date,
    notes text,
    topic text,
    kind text,
    action_vi text,
    sources jsonb,
    penalties jsonb,
    change_note text,
    calc text,
    reviewed boolean DEFAULT false NOT NULL,
    needs_review boolean DEFAULT false NOT NULL,
    review_reason text,
    proposed jsonb,
    content_sha256 text,
    load_run_id integer,
    reviewed_by text,
    reviewed_at timestamp with time zone
);


--
-- Name: chunks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunks ALTER COLUMN id SET DEFAULT nextval('public.chunks_id_seq'::regclass);


--
-- Name: legal_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents ALTER COLUMN id SET DEFAULT nextval('public.legal_documents_id_seq'::regclass);


--
-- Name: load_proposals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_proposals ALTER COLUMN id SET DEFAULT nextval('public.load_proposals_id_seq'::regclass);


--
-- Name: load_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_runs ALTER COLUMN id SET DEFAULT nextval('public.load_runs_id_seq'::regclass);


--
-- Name: chunks chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_pkey PRIMARY KEY (id);


--
-- Name: legal_documents legal_documents_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents
    ADD CONSTRAINT legal_documents_number_key UNIQUE (number);


--
-- Name: legal_documents legal_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents
    ADD CONSTRAINT legal_documents_pkey PRIMARY KEY (id);


--
-- Name: load_proposals load_proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_proposals
    ADD CONSTRAINT load_proposals_pkey PRIMARY KEY (id);


--
-- Name: load_runs load_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_runs
    ADD CONSTRAINT load_runs_pkey PRIMARY KEY (id);


--
-- Name: obligations obligations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.obligations
    ADD CONSTRAINT obligations_pkey PRIMARY KEY (id);


--
-- Name: chunks_client; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chunks_client ON public.chunks USING btree (client_profile_id);


--
-- Name: chunks_embedding; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chunks_embedding ON public.chunks USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: chunks_legal_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX chunks_legal_key ON public.chunks USING btree (document_id, ((locator ->> 'dieu'::text)), COALESCE((locator ->> 'khoan'::text), ''::text), ((locator ->> 'kind'::text)), COALESCE((locator ->> 'seq'::text), '0'::text)) WHERE (source_kind = 'legal_article'::text);


--
-- Name: chunks_tsv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chunks_tsv ON public.chunks USING gin (tsv);


--
-- Name: load_proposals_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX load_proposals_doc ON public.load_proposals USING btree (doc_code);


--
-- Name: load_proposals_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX load_proposals_status ON public.load_proposals USING btree (status, created_at);


--
-- Name: obligations_applies_when_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX obligations_applies_when_gin ON public.obligations USING gin (applies_when jsonb_path_ops);


--
-- Name: obligations_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX obligations_fts ON public.obligations USING gin (to_tsvector('public.vi_simple'::regconfig, COALESCE(duty_vi, ''::text)));


--
-- Name: chunks chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.legal_documents(id);


--
-- Name: chunks chunks_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chunks
    ADD CONSTRAINT chunks_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_runs(id);


--
-- Name: legal_documents legal_documents_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.legal_documents
    ADD CONSTRAINT legal_documents_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_runs(id);


--
-- Name: load_proposals load_proposals_applied_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.load_proposals
    ADD CONSTRAINT load_proposals_applied_run_id_fkey FOREIGN KEY (applied_run_id) REFERENCES public.load_runs(id);


--
-- Name: obligations obligations_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.obligations
    ADD CONSTRAINT obligations_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.legal_documents(id);


--
-- Name: obligations obligations_load_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.obligations
    ADD CONSTRAINT obligations_load_run_id_fkey FOREIGN KEY (load_run_id) REFERENCES public.load_runs(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 2oV7Fjq7ZVHvWz0jfnEbsFTHVWiUGyvZjLRXjIN45IeV99ficJhbFeyT3n5Xr1b

