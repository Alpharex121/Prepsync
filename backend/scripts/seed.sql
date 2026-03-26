INSERT INTO quiz_history (room_id, mode, config_params, question_package)
VALUES
(
    'sample_room_1',
    'QUIZ',
    '{"mode":"QUIZ","count":2,"time_per_q":30,"time_per_section":60,"topics":["Averages"],"exams":["SSC"]}'::jsonb,
    '{"questions":[{"text":"Sample question","options":["1","2","3","4"],"correct_index":1,"explanation":"Sample explanation","difficulty":"easy","topic":"Averages"}]}'::jsonb
)
ON CONFLICT DO NOTHING;

